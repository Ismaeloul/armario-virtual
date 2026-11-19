"""Uniqlo por API.SH (19-11-2026): conector, tope de créditos y clave cifrada. Sin red: las respuestas son
reales (de las pocas llamadas de prueba, recortadas) y salen de un transporte falso de httpx."""
import copy
import json
from datetime import date

import httpx
import pytest
from sqlalchemy import select
from test_shop import FIXTURES

from app import config
from app.db import SessionLocal
from app.models import Setting, ShopItem
from app.services import apish, shopping, shops, vault
from app.services.shops import NotThisStore, SearchError, crawl, uniqlo

KEY = "clave-de-prueba-1234567890"


def _json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeApi:
    """API.SH de mentira: guarda lo que se le pide y responde lo que se le diga por ruta."""

    def __init__(self, answers=None, status=200):
        self.answers = answers or {}  # ruta -> función(params) -> dict, o dict
        self.status = status
        self.calls: list[tuple[str, dict, str | None]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.calls.append((request.url.path, params, request.headers.get("x-api-key")))
        answer = self.answers.get(request.url.path, {})
        body = answer(params) if callable(answer) else answer
        return httpx.Response(self.status, json=body)


@pytest.fixture
def api(monkeypatch, client):
    def install(answers=None, status=200, key=KEY):
        fake = FakeApi(answers, status)
        monkeypatch.setattr(apish, "transport", httpx.MockTransport(fake))
        if key:
            with SessionLocal() as db:
                vault.save(db, apish.SECRET, key)
        return fake

    return install


def _page(products, next_page=None, credits=1):
    return {"total": len(products), "next_page": next_page, "count": len(products), "products": products,
            "cached": False, "credits_used": credits}


# ---------- Lectura


def test_solo_hombre_y_solo_fotos_de_producto_sin_modelo():
    data = _json("apish_uniqlo_search.json")
    products, ids, following, total = uniqlo.parse_search(data, "t-shirts")
    assert following == 2 and total == 543 and len(ids) == len(data["products"])
    # Las dos camisas de mujer, fuera; el T-shirt unisex solo tiene fotos con modelo (`eugoods`): fuera; los
    # bolsos no caben en el armario. Queda el T-shirt de Naruto, en su único color con foto de producto.
    assert [(p.product_ref, p.name, p.type, p.price_cents, p.old_price_cents) for p in products] == [
        ("uniqlo:E488252-000-00-30", "T-shirt UT MANGA 100th (Naruto)", "camiseta", 1990, None),
    ]
    product = products[0]
    assert product.url == "https://www.uniqlo.com/fr/fr/products/E488252-000/00?colorDisplayCode=30"
    detail = shops.cached_detail("uniqlo", product.store_data)  # la ficha sale de lo guardado: sin llamar
    assert detail.photo_urls and all("/WesternCommon/" in u and "/goods_" in u for u in detail.photo_urls)
    assert detail.sizes == [] and not detail.stock_known and detail.in_stock
    assert uniqlo.UniqloConnector().reference(product.store_data) == "488252"


def test_precio_rebajado():
    data = copy.deepcopy(_json("apish_uniqlo_search.json"))
    women = data["products"][0]
    women.update(gender_category="MEN", name="T-shirt rayé")  # la de mujer rebajada (48,30 € de 69 €), de hombre
    women["images_by_color"]["01"] = "https://image.uniqlo.com/UQ/ST3/WesternCommon/imagesgoods/488507/item/goods_01_488507_3x4.jpg"
    sale = next(p for p in uniqlo.parse_search(data, "t-shirts")[0] if "E488507" in p.product_ref)
    assert (sale.price_cents, sale.old_price_cents, sale.old_price_known) == (4830, 6900, True)


def test_consulta_pagina_con_next_page_y_limit_100(api):
    first = _json("apish_uniqlo_search.json")
    second = copy.deepcopy(first)
    for item in second["products"]:
        item["id"] = item["id"].replace("E4", "E9")
    fake = api({"/uniqlo/v1/search": lambda p: dict(first, next_page=2) if p["page"] == "1" else dict(second, next_page=None)})
    found = uniqlo.UniqloConnector().list_category("t-shirts")
    assert [p.product_ref for p in found] == ["uniqlo:E488252-000-00-30", "uniqlo:E988252-000-00-30"]
    assert [c[1]["page"] for c in fake.calls] == ["1", "2"]
    params = fake.calls[0][1]
    assert params == {"q": "t-shirt", "country": "fr", "category": "37609", "limit": "100", "sort": "newest",
                      "page": "1", "raw": "0"}
    assert all(c[0] == "/uniqlo/v1/search" and c[2] == KEY for c in fake.calls)  # la clave, solo en la cabecera
    assert apish.credits() == (2, config.APISH_MONTHLY_CREDITS)
    assert uniqlo.UniqloConnector().listed_all("t-shirts") is not False


def test_semana_normal_para_en_cuanto_todo_esta_visto(api):
    data = _json("apish_uniqlo_search.json")
    fake = api({"/uniqlo/v1/search": lambda p: dict(data, next_page=int(p["page"]) + 1)})
    connector = uniqlo.UniqloConnector()
    uniqlo.note_seen([p["id"] for p in data["products"]])
    uniqlo.mark_full("t-shirts")  # ya se recorrió entera este mes
    with SessionLocal() as db:  # y hay algo de Uniqlo guardado
        db.add(ShopItem(store="uniqlo", product_ref="uniqlo:x", name="x", price_cents=100, url="u", type="camiseta",
                        category="parte_superior", color="negro", pattern="liso", style="casual", season="todo",
                        status=shopping.CANDIDATE, batch=date(2026, 11, 1)))
        db.commit()
    connector.list_category("t-shirts")
    assert len(fake.calls) == 1 and connector.listed_all("t-shirts") is False  # una página, y no retira nada


def test_una_seccion_a_medias_no_retira_lo_guardado(api, monkeypatch):
    connector = shops.CONNECTORS["uniqlo"]
    product = uniqlo.parse_search(_json("apish_uniqlo_search.json"), "t-shirts")[0][0]
    monkeypatch.setattr(connector, "list_category", lambda slug: [product])
    monkeypatch.setattr(connector, "listed_all", lambda slug: False)
    api()
    with SessionLocal() as db:
        shopping.set_store(db, "uniqlo", True, ["t-shirts"])
        db.add(ShopItem(store="uniqlo", product_ref="uniqlo:antigua", name="Vieja", price_cents=100, url="u",
                        type="camiseta", category="parte_superior", color="negro", pattern="liso", style="casual",
                        season="todo", status=shopping.CANDIDATE, section="t-shirts", batch=date(2026, 11, 1)))
        db.commit()
        result = shopping.refresh_store(db, "uniqlo", limit=0)
        assert result["complete"] and result["found"] == 1
        assert db.scalars(select(ShopItem).where(ShopItem.product_ref == "uniqlo:antigua")).first() is not None
        # Leída entera (el recorrido del mes), sí se retira.
        monkeypatch.setattr(connector, "listed_all", lambda slug: True)
        shopping.refresh_store(db, "uniqlo", limit=0)
        db.expire_all()
        assert db.scalars(select(ShopItem).where(ShopItem.product_ref == "uniqlo:antigua")).first() is None


# ---------- Créditos


def test_tope_de_creditos_para_la_tienda(api, monkeypatch):
    monkeypatch.setattr(config, "APISH_MONTHLY_CREDITS", 3)
    fake = api({"/uniqlo/v1/search": lambda p: dict(_json("apish_uniqlo_search.json"), next_page=int(p["page"]) + 1,
                                                    credits_used=1)})
    with pytest.raises(crawl.Partial) as stopped:
        uniqlo.UniqloConnector().list_category("t-shirts")
    assert isinstance(stopped.value.cause, apish.QuotaReached) and len(fake.calls) == 3
    assert apish.credits() == (3, 3)
    why = shops.unavailable("uniqlo")
    assert why.startswith("Tope de créditos del mes alcanzado (3 de 3)")
    with SessionLocal() as db:
        assert not shopping.reachable(db, "uniqlo")
        shopping.set_store(db, "uniqlo", True, None)
        result = shopping.refresh_store(db, "uniqlo")
    assert len(fake.calls) == 3 and "Tope de créditos" in result["error"]  # ni una llamada más
    # El mes que viene se empieza de cero.
    apish.write_setting(apish.K_CREDITS, {"month": "2000-01", "used": 3})
    assert apish.credits()[0] == 0 and shops.unavailable("uniqlo") is None


def test_un_error_de_su_lado_no_cuenta_y_no_ensena_la_clave(api):
    api({"/uniqlo/v1/search": {"success": False, "error": f"Upstream failed for key {KEY}"}}, status=502)
    with pytest.raises(shops.ShopError) as error:
        uniqlo.UniqloConnector().list_category("t-shirts")
    assert KEY not in str(error.value) and "HTTP 502" in str(error.value)
    assert apish.credits()[0] == 0
    api({"/uniqlo/v1/search": {"success": False, "error": "Invalid API key"}}, status=401, key=None)
    with pytest.raises(shops.BlockedError, match="rechaza la clave"):
        uniqlo.UniqloConnector().list_category("t-shirts")


# ---------- La clave


def test_sin_clave_no_se_llama(api):
    fake = api(key=None)
    assert shops.unavailable("uniqlo").startswith("Falta la clave de API")
    with SessionLocal() as db:
        shopping.set_store(db, "uniqlo", True, None)
        result = shopping.refresh_store(db, "uniqlo")
    assert "Falta la clave de API" in result["error"] and "Ajustes" in result["error"] and fake.calls == []
    with pytest.raises(SearchError, match="falta la clave"):
        uniqlo.UniqloConnector().search("https://www.uniqlo.com/fr/fr/products/E422992-000/00")
    with pytest.raises(NotThisStore):
        uniqlo.UniqloConnector().search("t-shirt blanc")
    assert fake.calls == []


def test_la_clave_se_guarda_cifrada_en_ajustes_y_nunca_se_devuelve(client, api):
    fake = api(key=None)
    uniqlo_row = lambda: next(s for s in client.get("/api/shop/state").json()["stores"] if s["key"] == "uniqlo")  # noqa: E731
    before = client.get("/api/settings").json()["apish"]
    assert before == {"has_key": False, "from_env": False, "credits_used": 0,
                      "credits_limit": config.APISH_MONTHLY_CREDITS}
    row = uniqlo_row()
    assert row["apish"] is True and row["unavailable"].startswith("Falta la clave de API")
    assert all(not s["apish"] for s in client.get("/api/shop/state").json()["stores"] if s["key"] != "uniqlo")

    response = client.put("/api/settings/apish-key", json={"key": KEY})
    assert response.status_code == 200 and KEY not in response.text
    assert response.json()["apish"]["has_key"] is True and uniqlo_row()["unavailable"] is None
    assert KEY not in client.get("/api/settings").text and KEY not in client.get("/api/shop/state").text
    with SessionLocal() as db:
        stored = db.get(Setting, "secret_apish").value
        assert KEY not in stored and KEY not in json.dumps([r.value for r in db.scalars(select(Setting))])
        assert vault.get(db, apish.SECRET) == KEY
    # La clave maestra va aparte, fuera de data/.
    master = vault.secrets_dir() / vault.MASTER_FILE
    assert master.exists() and config.DATA_DIR not in master.parents

    # Algo que no es una clave, o un campo mal puesto: el error no repite lo recibido.
    for body in ({"key": "con espacios " + KEY}, {"apikey": KEY}, KEY):
        response = client.put("/api/settings/apish-key", json=body)
        assert response.status_code == 400 and KEY not in response.text
    response = client.put("/api/settings/apish-key", content=b"no es json " + KEY.encode())
    assert response.status_code == 400 and KEY not in response.text

    # Sin la clave maestra (otro equipo, volumen perdido): como si no hubiera clave, sin romper nada.
    content = master.read_bytes()
    master.unlink()
    assert uniqlo_row()["unavailable"].startswith("Falta la clave de API")
    assert client.get("/api/settings").json()["apish"]["has_key"] is False
    master.write_bytes(content)

    response = client.delete("/api/settings/apish-key")
    assert response.status_code == 200 and response.json()["apish"]["has_key"] is False
    with SessionLocal() as db:
        assert db.get(Setting, "secret_apish") is None
    assert fake.calls == []


def test_los_creditos_se_ven_en_ajustes(client, api):
    api({"/uniqlo/v1/search": _page([], credits=1)})
    uniqlo.UniqloConnector().list_category("t-shirts")
    assert client.get("/api/settings").json()["apish"]["credits_used"] == 1


def test_la_variable_de_entorno_manda(api, monkeypatch):
    fake = api({"/uniqlo/v1/search": _page([])})
    monkeypatch.setenv("ARMARIO_APISH_KEY", "otra-clave-de-desarrollo")
    uniqlo.UniqloConnector().list_category("t-shirts")
    assert fake.calls[0][2] == "otra-clave-de-desarrollo"


# ---------- El buscador


def test_buscador_por_enlace_pide_la_ficha(api):
    product = copy.deepcopy(_json("apish_uniqlo_product.json"))
    # La ficha real solo tenía fotos con modelo en sus tres colores: se le añade uno con foto de producto.
    product["colors"].append({"code": "12", "name": "GRIS", "group": "GRAY"})
    product["skus"].append({"color_code": "12", "size": "M", "size_code": "004", "stock_status": "IN_STOCK"})
    fake = api({"/uniqlo/v1/product": product})
    found = uniqlo.UniqloConnector().search(
        "mira https://www.uniqlo.com/fr/fr/products/E422992-000/00?colorDisplayCode=12 esta")
    assert [p.product_ref for p in found] == ["uniqlo:E422992-000-00-12"]
    assert fake.calls == [("/uniqlo/v1/product", {"id": "E422992-000", "country": "fr", "raw": "0"}, KEY)]
    detail = shops.cached_detail("uniqlo", found[0].store_data)
    assert detail.stock_known and {"name": "M", "in_stock": True} in detail.sizes
    assert detail.composition == "100% Coton"
    assert (found[0].price_cents, found[0].old_price_cents) == (1490, 1990)

    # Sin color con foto de producto: se explica (y la llamada ya se ha gastado).
    api({"/uniqlo/v1/product": _json("apish_uniqlo_product.json")})
    with pytest.raises(SearchError, match="fotos con modelo"):
        uniqlo.UniqloConnector().search("https://www.uniqlo.com/fr/fr/products/E422992-000/00")
    # Un enlace de otra tienda no es cosa suya.
    with pytest.raises(NotThisStore):
        uniqlo.UniqloConnector().search("https://www.zara.com/fr/fr/x-p1.html")


def test_buscador_de_texto_solo_con_la_tienda_activada(api):
    fake = api({"/uniqlo/v1/search": _json("apish_uniqlo_search.json")})
    with pytest.raises(NotThisStore):
        uniqlo.UniqloConnector().search("t-shirt naruto")
    assert fake.calls == []
    with SessionLocal() as db:
        shopping.set_store(db, "uniqlo", True, None)
    found = uniqlo.UniqloConnector().search("t-shirt naruto")
    assert [p.product_ref for p in found] == ["uniqlo:E488252-000-00-30"]
    assert fake.calls[0][1]["q"] == "t-shirt naruto" and fake.calls[0][1]["category"] == "37609"


def test_lo_visto_se_olvida_con_el_tiempo(client):
    uniqlo.note_seen(["E1"], today=date(2026, 1, 1))
    uniqlo.note_seen(["E2"], today=date(2026, 11, 1))
    assert set(uniqlo.seen_ids()) == {"E2"}
