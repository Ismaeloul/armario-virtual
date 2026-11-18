"""Compras (Fase 4). Todo sin red: un conector falso y JSON de ejemplo recortado de Zara."""
import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from conftest import VALID_DRAFT, FakeAnalyzer
from sqlalchemy import select

from app import catalog
from app.db import SessionLocal
from app.main import referenced_photos
from app.models import ShopItem, now_utc
from app.services import outfits, shopping, shops, storage
from app.services.ai.base import AnalysisError
from app.services.shops import ShopDetail, ShopError, ShopProduct, estimate, zara

FIXTURES = Path(__file__).parent / "fixtures"
INVIERNO, VERANO = date(2026, 11, 18), date(2026, 7, 1)  # miércoles los dos
VIERNES = date(2026, 11, 20)


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def product(ref: str, type: str = "camisa", color: str = "blanco", price: int = 2995, section: str = "camisas",
            **extra) -> ShopProduct:
    return ShopProduct(
        store="zara", product_ref=f"zara:{ref}", name=extra.pop("name", f"{type.capitalize()} {ref}"),
        price_cents=price, url=f"https://tienda.test/{ref}", store_color=color.capitalize(), section=section,
        type=type, category=catalog.category_of(type), color=color, pattern=extra.pop("pattern", "liso"),
        style=extra.pop("style", "casual"), season=extra.pop("season", "todo_el_ano"),
        details=extra.pop("details", ""), store_data={"ref": ref},
    )


class FakeConnector:
    """Una tienda de mentira: devuelve lo que se le diga y apunta lo que se le pide."""

    key = "zara"
    name = "Zara"
    refresh_weekday = 4  # viernes
    categories = {"camisas": "Camisas", "pantalones": "Pantalones", "sudaderas": "Sudaderas"}

    def __init__(self, photo: bytes, **by_section: list[ShopProduct]):
        self.photo = photo
        self.products = by_section
        self.failing: set[str] = set()  # categorías que fallan
        self.gone: set[str] = set()  # productos que ya no existen
        self.details: dict[str, ShopDetail] = {}
        self.calls: list[tuple[str, str]] = []

    def list_category(self, slug):
        self.calls.append(("lista", slug))
        if slug in self.failing:
            raise ShopError("HTTP 403")
        return list(self.products.get(slug, []))

    def detail(self, store_data):
        ref = store_data["ref"]
        self.calls.append(("detalle", ref))
        if ref in self.gone:
            return None
        return self.details.get(ref) or ShopDetail(
            price_cents=None,
            sizes=[{"name": "M", "in_stock": True}, {"name": "L", "in_stock": False}],
            photo_urls=[f"https://fotos.test/{ref}-e1.jpg", f"https://fotos.test/{ref}-e2.jpg"],
            description="Manga larga.",
            color_hex="#101010",
        )

    def download(self, url):
        self.calls.append(("foto", url))
        return self.photo

    def asked(self, kind: str) -> list[str]:
        return [what for k, what in self.calls if k == kind]


@pytest.fixture
def tienda(monkeypatch, photo_bytes):
    """Instala la tienda falsa y la deja activada."""

    def install(**by_section) -> FakeConnector:
        connector = FakeConnector(photo_bytes, **by_section)
        monkeypatch.setitem(shops.CONNECTORS, "zara", connector)
        with SessionLocal() as db:
            shopping.set_store(db, "zara", True, None)
        return connector

    return install


def _refresh(today: date = INVIERNO, **kwargs) -> dict:
    with SessionLocal() as db:
        return shopping.refresh(db, today=today, **kwargs)


def _items(status: str | None = None) -> list[ShopItem]:
    with SessionLocal() as db:
        stmt = select(ShopItem).order_by(ShopItem.id)
        return list(db.scalars(stmt.where(ShopItem.status == status) if status else stmt))


def _garment(client, photo_bytes, **fields) -> dict:
    photo = client.post(
        "/api/garments/analyze", files={"front": ("f.jpg", photo_bytes, "image/jpeg")}, data={"skip_ai": "true"}
    ).json()["photo_front"]["id"]
    body = {k: v for k, v in VALID_DRAFT.items() if k != "confidence"}
    body.update({"photo_front": photo, **fields})
    created = client.post("/api/garments", json=body)
    assert created.status_code == 201
    return created.json()


def _item(id=1, type="vaquero", color="azul", season="todo_el_ano", style="casual", pattern="liso") -> outfits.Item:
    return outfits.Item(
        id=id, type=type, category=catalog.category_of(type), color=color, style=style, season=season, pattern=pattern
    )


# ---------- El conector de Zara


def test_el_parser_de_zara_normaliza_los_productos_y_se_salta_lo_que_no_vale():
    products = zara.parse_category(_fixture("zara_categoria.json"), "hombre-sobrecamisas-l3174")

    # Fuera: el que no tiene nombre, el que no es «Product», el que no trae seo, los calcetines y el repetido.
    assert [p.name for p in products] == [
        "Sobrecamisa estructura brillo",
        "Sobrecamisa regular fit efecto ante",
        "Sobrecamisa regular fit cuadros",
        "Sobrecamisa regular fit efecto ante",
    ]
    assert len({p.product_ref for p in products}) == 4  # el mismo modelo en dos colores son dos productos

    first = products[0]
    assert first.store == "zara" and first.product_ref == "zara:05854122-800"
    assert first.price_cents == 6995
    assert first.url == "https://www.zara.com/es/es/sobrecamisa-estructura-brillo-p05854122.html?v1=590649460"
    assert first.store_color == "Negro"
    assert (first.type, first.category, first.color) == ("sobrecamisa", "capa_exterior", "negro")
    assert (first.pattern, first.style, first.season) == ("texturizado", "casual", "todo_el_ano")
    assert [(p.store_color, p.color) for p in products[1:]] == [
        ("Coñac", "marrón"), ("Khaki", "verde oliva"), ("Blanco roto", "crudo"),
    ]
    assert products[2].pattern == "cuadros"


def test_un_keyword_de_zara_con_espacios_se_arregla_para_que_el_enlace_funcione():
    data = _fixture("zara_categoria.json")
    item = data["productGroups"][0]["elements"][0]["commercialComponents"][0]
    item["seo"]["keyword"] = "sobrecamisa-estructura\u00a0brillo"  # espacio de no separación, visto en la web real
    first = zara.parse_category(data, "hombre-sobrecamisas-l3174")[0]
    assert first.store_data["keyword"] == "sobrecamisa-estructura-brillo"
    assert first.url == "https://www.zara.com/es/es/sobrecamisa-estructura-brillo-p05854122.html?v1=590649460"


def test_zara_redirige_con_un_278_y_los_fallos_se_cuentan_en_claro(monkeypatch):
    import httpx

    connector = zara.ZaraConnector(pause=0)
    good = zara.BASE + "/buena-p1.html?v1=1&ajax=true"
    answers = {
        zara.BASE + "/mala-p1.html?v1=1&ajax=true": httpx.Response(278, json={"location": good, "body": {}}),
        good: httpx.Response(200, json=_fixture("zara_detalle.json")),
        zara.BASE + "/gone-p1.html?v1=1&ajax=true": httpx.Response(410, json={}),
        zara.BASE + "/bloqueo-p1.html?v1=1&ajax=true": httpx.Response(403, text="Access Denied"),
        zara.BASE + "/html-p1.html?v1=1&ajax=true": httpx.Response(200, text="<html>captcha</html>"),
    }
    asked = []

    def fake_get(self, url, pause, headers=None):
        asked.append(url)
        if "lenta" in url:
            raise ShopError("tiempo agotado (20 s)")
        return answers[url]

    monkeypatch.setattr(zara.ZaraConnector, "_get", fake_get)
    data = {"seo_id": "1", "discern_id": 1, "color_id": "800"}

    assert connector.detail({**data, "keyword": "mala"}).price_cents == 6995 and asked[-1] == good
    assert connector.detail({**data, "keyword": "gone"}) is None  # ya no existe: no es un fallo
    for keyword, message in [
        ("bloqueo", "HTTP 403"), ("html", "la respuesta no era la esperada (no es JSON)"), ("lenta", "tiempo agotado (20 s)"),
    ]:
        with pytest.raises(ShopError, match=message.replace("(", r"\(").replace(")", r"\)")):
            connector.detail({**data, "keyword": keyword})


def test_el_detalle_de_zara_da_fotos_de_producto_tallas_y_precio():
    store_data = {"keyword": "sobrecamisa-estructura-brillo", "seo_id": "05854122", "discern_id": 590649460,
                  "color_id": "800"}
    data = _fixture("zara_detalle.json")
    detail = zara.parse_detail(data, store_data)

    # Solo las fotos sin modelo (-e1, -e2…), en orden, como mucho tres, y con la URL de la CDN.
    assert [url.rsplit("/", 1)[1] for url in detail.photo_urls] == [
        "05854122800-e1.jpg?w=1280", "05854122800-e2.jpg?w=1280", "05854122800-e4.jpg?w=1280",
    ]
    assert detail.photo_urls[0].startswith("https://static.zara.net/assets/public/")
    assert "/assets/public//" not in detail.photo_urls[0] and "public/assets" not in detail.photo_urls[0]
    assert detail.sizes[:2] == [{"name": "S", "in_stock": False}, {"name": "M", "in_stock": True}]
    assert detail.in_stock and detail.price_cents == 6995 and detail.color_hex == "#0a0a0a"
    assert "Sobrecamisa regular fit" in detail.description

    # Sin la foto -e1 no hay nada que enseñar: quien llama descarta el producto.
    color = data["product"]["detail"]["colors"][0]
    color["xmedia"] = [m for m in color["xmedia"] if not m["name"].endswith("-e1")]
    assert zara.parse_detail(data, store_data).photo_urls == []
    assert zara.parse_detail({"product": {"detail": {"colors": []}}}, store_data) is None


@pytest.mark.parametrize(
    ("name", "default", "expected"),
    [
        ("JEANS SLIM FIT", "vaquero", "vaquero"),
        ("SLIM FIT", "vaquero", "vaquero"),
        ("BERMUDA DENIM", "pantalón corto", "pantalón corto"),
        ("PANTALÓN CHINO SLIM", "pantalón", "chino"),
        ("CHINO CONFORT", "pantalón", "chino"),
        ("PANTALÓN CHÁNDAL BÁSICO", "pantalón", "chándal"),
        ("PANTALÓN JOGGER", "pantalón", "chándal"),
        ("PANTALÓN WIDE FIT", "pantalón", "pantalón"),
        ("POLO PUNTO TEXTURA", "jersey", "polo"),
        ("CUELLO CISNE BÁSICO", "jersey", "jersey"),
        ("CÁRDIGAN CREMALLERA", "jersey", "jersey"),
        ("CAMISA DENIM", "camisa", "camisa"),
        ("CAMISETA BÁSICA HEAVY WEIGHT", "camiseta", "camiseta"),
        ("CAZADORA VAQUERA", "chaqueta", "chaqueta"),
        ("ABRIGO LANA", "chaqueta", "abrigo"),
        ("BOTÍN CHELSEA PIEL", "zapatillas", "botas"),
        ("MOCASÍN PIEL", "zapatillas", "zapatos"),
        ("ZAPATILLA ESTILO RETRO", "zapatillas", "zapatillas"),
        ("PACK CALCETINES", "camiseta", None),
    ],
)
def test_el_tipo_sale_del_nombre_y_si_no_de_la_categoria(name, default, expected):
    assert estimate.estimate_type(name, default) == expected


@pytest.mark.parametrize(
    ("store_color", "expected"),
    [
        ("Negro", "negro"), ("Marino", "azul marino"), ("Azul marino", "azul marino"), ("Khaki", "verde oliva"),
        ("Crudo", "crudo"), ("Blanco Hueso", "crudo"), ("Gris vigoré", "gris"), ("Marrón chocolate", "marrón"),
        ("Rojo Burgundy", "burdeos"), ("Azul claro", "celeste"), ("Tostado", "marrón"), ("Arena", "beige"),
        ("Azul", "azul"), ("Verde botella", "verde"), ("Mostaza", "amarillo"), ("Color raro", "multicolor"),
    ],
)
def test_el_color_de_la_tienda_se_pasa_a_la_paleta(store_color, expected):
    assert estimate.estimate_color(store_color) == expected
    assert expected in catalog.COLORS


def test_estimacion_de_estampado_estilo_temporada_y_color_por_tono():
    assert estimate.estimate_color("Color raro", "#101010") == "negro"  # sin palabra conocida, el tono más cercano
    assert estimate.estimate_pattern("CAMISA RAYAS OXFORD") == "rayas"
    assert estimate.estimate_pattern("SOBRECAMISA CUADROS") == "cuadros"
    assert estimate.estimate_pattern("CAMISETA ESTAMPADO GRÁFICO") == "gráfico"
    assert estimate.estimate_pattern("CAMISETA PRINT ESPALDA") == "gráfico"
    assert estimate.estimate_pattern("JERSEY BÁSICO") == "liso"
    assert estimate.estimate_style("PANTALÓN CHÁNDAL", "chándal") == "deportivo"
    assert estimate.estimate_style("CAMISETA TÉCNICA TRAINING", "camiseta") == "deportivo"
    assert estimate.estimate_style("CAMISA OXFORD", "camisa") == "smart casual"
    assert estimate.estimate_style("PANTALÓN TRAJE", "pantalón") == "smart casual"
    assert estimate.estimate_style("SUDADERA CAPUCHA", "sudadera") == "casual"
    assert estimate.estimate_season("SUDADERA CAPUCHA", "sudadera") == "invierno"
    assert estimate.estimate_season("BERMUDA CHINO", "pantalón corto") == "verano"
    assert estimate.estimate_season("CAMISA LINO", "camisa") == "verano"
    assert estimate.estimate_season("CAZADORA ACOLCHADA", "chaqueta") == "invierno"
    assert estimate.estimate_season("JEANS SLIM", "vaquero") == "todo_el_ano"
    assert estimate.sentence_case("SOBRECAMISA  BOXY FIT") == "Sobrecamisa boxy fit"


# ---------- La nota


def test_la_nota_premia_los_huecos_del_armario():
    wardrobe = [_item(1, "vaquero", "azul"), _item(2, "camiseta", "blanco"), _item(3, "camiseta", "negro"),
                _item(4, "sudadera", "gris"), _item(5, "zapatillas", "blanco")]

    nueva, motivos = shopping.score(product("a", "sobrecamisa", "verde oliva"), wardrobe)
    texts = [m["text"] for m in motivos]
    assert "No tienes ninguna sobrecamisa" in texts
    assert any(t.startswith("Combina con ") for t in texts)

    otro_color, motivos = shopping.score(product("b", "camiseta", "gris"), wardrobe)
    assert "No tienes ninguna camiseta gris" in [m["text"] for m in motivos]
    assert nueva > otro_color  # un tipo que falta pesa más que un color que falta

    _, motivos = shopping.score(product("c", "botas", "marrón"), wardrobe)
    texts = [m["text"] for m in motivos]
    assert "No tienes botas" in texts and "Solo tienes 1 par de zapatos" in texts


def test_la_nota_penaliza_repetir_lo_que_ya_hay():
    wardrobe = [_item(1, "vaquero", "azul"), _item(2, "sudadera", "negro"), _item(3, "sudadera", "negro"),
                _item(4, "sudadera", "negro"), _item(5, "sudadera", "gris"), _item(6, "zapatillas", "blanco")]

    repetida, motivos = shopping.score(product("a", "sudadera", "negro"), wardrobe)
    contra = [m["text"] for m in motivos if m["kind"] == "contra"]
    assert contra == ["Ya tienes 3 sudaderas negras"]

    distinta, _ = shopping.score(product("b", "sudadera", "verde oliva"), wardrobe)
    una_vez, motivos = shopping.score(product("c", "sudadera", "gris"), wardrobe)
    assert "Ya tienes 1 sudadera gris" in [m["text"] for m in motivos]
    assert distinta > una_vez > repetida


def test_la_nota_aprende_de_los_me_gusta_de_la_tienda():
    wardrobe = [_item(1, "vaquero", "azul"), _item(2, "camisa", "blanco")]
    prefs = shopping.ShopTaste()
    for _ in range(4):
        prefs.learn(product("x", "sobrecamisa", "negro", price=4995), liked=True)
        prefs.learn(product("y", "polo", "rosa", price=1995), liked=False)

    gusta, motivos = shopping.score(product("a", "sobrecamisa", "negro", price=3995), wardrobe, prefs=prefs)
    neutra, _ = shopping.score(product("a", "sobrecamisa", "negro", price=3995), wardrobe, prefs=shopping.ShopTaste())
    texts = [m["text"] for m in motivos]
    assert gusta > neutra
    assert "Te suelen gustar las sobrecamisas" in texts and "Te suele gustar el negro" in texts

    no_gusta, motivos = shopping.score(product("b", "polo", "rosa", price=1995), wardrobe, prefs=prefs)
    sin_opinion, _ = shopping.score(product("b", "polo", "rosa", price=1995), wardrobe, prefs=shopping.ShopTaste())
    assert no_gusta < sin_opinion
    assert {"Sueles descartar los polos", "Sueles descartar el rosa", "Sueles descartar este rango de precio"} <= {
        m["text"] for m in motivos if m["kind"] == "contra"
    }


def test_fuera_de_mayo_a_septiembre_no_se_propone_ropa_de_verano():
    bermuda = product("a", "pantalón corto", "beige", season="verano")
    camiseta = product("b", "camiseta", "blanco")
    manga_larga = product("c", "camiseta", "blanco", details="camiseta manga larga")
    assert [shopping.out_of_season(p, INVIERNO) for p in (bermuda, camiseta, manga_larga)] == [True, True, False]
    assert not any(shopping.out_of_season(p, VERANO) for p in (bermuda, camiseta, manga_larga))


# ---------- La tanda


def test_la_tanda_guarda_las_mejores_con_fotos_y_reparte_entre_categorias(client, tienda):
    connector = tienda(
        camisas=[product(f"c{i}", "camisa", "blanco") for i in range(6)],
        pantalones=[product(f"p{i}", "vaquero", "azul", section="pantalones") for i in range(6)],
    )
    result = _refresh(limit=4)

    assert result["ok"] and result["found"] == 12 and result["added"] == 4 and not result["errors"]
    items = _items()
    assert sorted(i.section for i in items) == ["camisas", "camisas", "pantalones", "pantalones"]  # no 4 camisas
    assert all(i.status == "nuevo" and i.batch == INVIERNO for i in items)
    # El detalle y las fotos solo se piden de las elegidas.
    assert len(connector.asked("detalle")) == 4 and len(connector.asked("foto")) == 8
    for item in items:
        assert len(item.photos) == 2 and all(storage.exists(p) for p in item.photos)
        assert item.sizes == [{"name": "M", "in_stock": True}, {"name": "L", "in_stock": False}]
        assert item.store_color_hex == "#101010" and item.reasons
    assert set(items[0].photos) <= referenced_photos()  # la limpieza de fotos huérfanas no las toca

    state = client.get("/api/shop/state").json()
    assert state["pending"] == 4
    status = state["stores"][0]["status"]
    assert status["at"] and {k: status[k] for k in ("state", "found", "added", "failed", "error")} == {
        "state": "ok", "found": 12, "added": 4, "failed": 0, "error": None,
    }


def test_lo_ya_visto_no_se_vuelve_a_proponer_y_lo_pendiente_caduca(client, tienda):
    connector = tienda(camisas=[product("a"), product("b"), product("c")])
    assert _refresh(limit=2)["added"] == 2
    first = _items()
    client.post(f"/api/shop/items/{first[0].id}/dislike")
    old_photos = first[1].photos

    # Una semana después: lo descartado y lo que caducó sin ver no vuelven; entra lo que no se había visto.
    connector.products["camisas"].append(product("d"))
    result = _refresh(today=INVIERNO + timedelta(days=7))
    by_ref = {i.product_ref: i.status for i in _items()}
    seen_before = {first[0].product_ref: "descartado", first[1].product_ref: "caducado"}
    assert seen_before.items() <= by_ref.items()
    assert sorted(by_ref.values()) == ["caducado", "descartado", "nuevo", "nuevo"]
    assert by_ref["zara:d"] == "nuevo" and result["added"] == 2 and result["expired"] == 1
    assert not any(storage.exists(p) for p in old_photos)  # lo caducado no deja fotos en el disco

    # Y otra más sin novedades: nada que añadir, y nada de lo anterior resucita.
    assert _refresh(today=INVIERNO + timedelta(days=14))["added"] == 0
    assert [i.status for i in _items()].count("nuevo") == 0


def test_la_tanda_sigue_aunque_falle_una_categoria_o_un_producto(client, tienda):
    connector = tienda(
        camisas=[product("a"), product("sin-foto"), product("agotado"), product("ya-no-existe")],
        pantalones=[product("p", "vaquero", "azul", section="pantalones")],
    )
    connector.failing.add("sudaderas")
    connector.gone.add("ya-no-existe")
    connector.details["sin-foto"] = ShopDetail(price_cents=1000, sizes=[{"name": "M", "in_stock": True}], photo_urls=[])
    connector.details["agotado"] = ShopDetail(
        price_cents=1000, sizes=[{"name": "M", "in_stock": False}], photo_urls=["https://fotos.test/x-e1.jpg"]
    )
    result = _refresh()

    assert result["ok"] and result["errors"] == ["Sudaderas: HTTP 403"]
    assert sorted(i.product_ref for i in _items()) == ["zara:a", "zara:p"]
    # Funciona, pero el panel «Tiendas» enseña la petición que falló y por qué.
    status = client.get("/api/shop/state").json()["stores"][0]["status"]
    assert (status["state"], status["found"], status["added"]) == ("ok", 5, 2)
    assert (status["failed"], status["error"]) == (1, "Sudaderas: HTTP 403")


def test_un_conector_roto_tampoco_tumba_la_tanda(client, tienda):
    connector = tienda(camisas=[product("a")])
    connector.list_category = lambda slug: {}["no-existe"]  # un fallo de programación, no de la tienda
    result = _refresh()
    assert not result["ok"] and result["failed"] == 3
    status = client.get("/api/shop/state").json()["stores"][0]["status"]
    assert status["state"] == "failed" and status["error"] == "Camisas: error inesperado en el conector"


def test_si_la_tienda_no_responde_no_se_pierde_nada_y_se_reintenta(client, tienda):
    connector = tienda(camisas=[product("a")])
    _refresh()
    connector.failing.update(connector.categories)
    result = _refresh(today=INVIERNO + timedelta(days=7))

    assert not result["ok"] and len(result["errors"]) == 3
    assert [i.status for i in _items()] == ["nuevo"]  # la propuesta de la semana pasada sigue ahí
    # El fallo no rompe nada: se guarda y se enseña en el panel, con el motivo en claro.
    store = client.get("/api/shop/state").json()["stores"][0]
    assert store["status"]["state"] == "failed" and store["status"]["at"]
    assert (store["status"]["found"], store["status"]["failed"]) == (0, 3)
    assert store["status"]["error"] == "Camisas: HTTP 403"


def test_cada_tienda_se_consulta_en_su_dia_de_la_semana(client, tienda):
    connector = tienda(camisas=[product("a")])
    jueves, sabado, lunes = VIERNES - timedelta(days=1), VIERNES + timedelta(days=1), VIERNES + timedelta(days=3)
    assert shopping.check_day("zara", VIERNES) == VIERNES
    assert shopping.check_day("zara", jueves) == VIERNES - timedelta(days=7)

    with SessionLocal() as db:
        # Nunca consultada: toca en cuanto se activa, sea el día que sea.
        assert shopping.is_due(db, "zara", INVIERNO) and shopping.due_stores(db, INVIERNO) == ["zara"]
        assert shopping.next_check(db, "zara", INVIERNO) == INVIERNO

        # Consultada con éxito un miércoles («Consultar ahora»): ya no toca hasta el viernes.
        shopping.refresh(db, today=INVIERNO)
        assert not shopping.is_due(db, "zara", INVIERNO) and not shopping.is_due(db, "zara", jueves)
        assert shopping.next_check(db, "zara", jueves) == VIERNES
        assert shopping.is_due(db, "zara", VIERNES)
        # Si la app estaba apagada el viernes, se hace al arrancar el sábado o el lunes.
        assert shopping.is_due(db, "zara", sabado) and shopping.is_due(db, "zara", lunes)

        # El viernes falla: hoy no se insiste; mañana sí, y como mucho una vez al día.
        connector.failing.update(connector.categories)
        assert not shopping.refresh(db, today=VIERNES)["ok"]
        assert not shopping.is_due(db, "zara", VIERNES)
        assert shopping.next_check(db, "zara", VIERNES) == sabado
        assert shopping.is_due(db, "zara", sabado)
        assert not shopping.refresh(db, today=sabado)["ok"]
        assert not shopping.is_due(db, "zara", sabado) and shopping.is_due(db, "zara", sabado + timedelta(days=1))

        # El lunes por fin responde: hasta el viernes siguiente no vuelve a tocar.
        connector.failing.clear()
        assert shopping.refresh(db, today=lunes)["ok"]
        assert not shopping.is_due(db, "zara", lunes) and not shopping.is_due(db, "zara", lunes + timedelta(days=3))
        assert shopping.next_check(db, "zara", lunes) == VIERNES + timedelta(days=7)
        assert shopping.is_due(db, "zara", VIERNES + timedelta(days=7))

        # Desactivada no se consulta nunca.
        shopping.set_store(db, "zara", False, None)
        assert not shopping.is_due(db, "zara", VIERNES + timedelta(days=7))
    assert client.get("/api/shop/state").json()["stores"][0]["next_check"] is None


def test_fuera_de_temporada_la_tanda_no_trae_ropa_de_verano(client, tienda):
    tienda(pantalones=[
        product("bermuda", "pantalón corto", "beige", section="pantalones", season="verano"),
        product("vaquero", "vaquero", "azul", section="pantalones"),
    ])
    _refresh(today=INVIERNO)
    assert [i.product_ref for i in _items()] == ["zara:vaquero"]


def test_los_me_gusta_caducan_si_el_producto_desaparece_se_agota_o_pasan_30_dias(client, tienda):
    connector = tienda(camisas=[product("sigue"), product("desaparece"), product("se-agota"), product("viejo")])
    _refresh()
    for item in _items():
        assert client.post(f"/api/shop/items/{item.id}/like").status_code == 200
    assert len(client.get("/api/shop/liked").json()) == 4

    connector.gone.add("desaparece")
    connector.details["se-agota"] = ShopDetail(
        price_cents=2995, sizes=[{"name": "M", "in_stock": False}], photo_urls=["https://fotos.test/x-e1.jpg"]
    )
    connector.details["sigue"] = ShopDetail(
        price_cents=1995, sizes=[{"name": "S", "in_stock": True}], photo_urls=["https://fotos.test/x-e1.jpg"]
    )
    with SessionLocal() as db:
        old = db.scalars(select(ShopItem).where(ShopItem.product_ref == "zara:viejo")).one()
        old.liked_at = now_utc() - timedelta(days=31)
        old.expires_at = now_utc() - timedelta(days=1)
        soon = db.scalars(select(ShopItem).where(ShopItem.product_ref == "zara:sigue")).one()
        soon.expires_at = now_utc() + timedelta(days=3)
        db.commit()
    connector.calls.clear()
    _refresh(today=INVIERNO + timedelta(days=7))

    by_ref = {i.product_ref: i for i in _items()}
    assert {ref: i.status for ref, i in by_ref.items()} == {
        "zara:sigue": "gustado", "zara:desaparece": "caducado", "zara:se-agota": "caducado", "zara:viejo": "caducado",
    }
    assert "viejo" not in connector.asked("detalle")  # por fecha: ni se pregunta a la tienda
    liked = client.get("/api/shop/liked").json()
    assert [(i["name"], i["price_cents"], i["sizes"], i["expires_soon"]) for i in liked] == [
        ("Camisa sigue", 1995, [{"name": "S", "in_stock": True}], True)  # precio y tallas al día
    ]


# ---------- La API


def test_la_tienda_arranca_desactivada_y_se_configura_en_la_pestana(client, monkeypatch, photo_bytes):
    connector = FakeConnector(photo_bytes, camisas=[product("a")], pantalones=[product("p", "vaquero", "azul")])
    monkeypatch.setitem(shops.CONNECTORS, "zara", connector)

    state = client.get("/api/shop/state").json()
    assert [(s["key"], s["name"], s["enabled"]) for s in state["stores"]] == [("zara", "Zara", False)]
    assert all(c["enabled"] for c in state["stores"][0]["categories"])
    assert state["running"] is False and state["pending"] == 0
    assert state["stores"][0]["weekday"] == 4 and state["stores"][0]["next_check"] is None
    assert state["stores"][0]["status"] == {
        "state": "never", "at": None, "found": 0, "added": 0, "failed": 0, "error": None,
    }
    assert client.post("/api/shop/refresh").status_code == 409  # sin tienda activada no hay tanda
    assert client.post("/api/shop/refresh", json={"store": "zara"}).status_code == 409
    assert client.post("/api/shop/refresh", json={"store": "otra"}).status_code == 404
    assert client.get("/api/shop/next").json() == {"item": None, "remaining": 0}
    with SessionLocal() as db:
        assert shopping.due_stores(db) == []

    state = client.patch("/api/shop/settings", json={"store": "zara", "enabled": True, "categories": ["camisas"]}).json()
    assert state["stores"][0]["enabled"] is True
    assert [c["slug"] for c in state["stores"][0]["categories"] if c["enabled"]] == ["camisas"]
    assert client.patch("/api/shop/settings", json={"store": "otra", "enabled": True}).status_code == 404
    with SessionLocal() as db:
        assert shopping.due_stores(db) == ["zara"]

    # «Consultar ahora» lanza la consulta en segundo plano y la petición vuelve ya.
    assert client.post("/api/shop/refresh", json={"store": "zara"}).status_code == 202
    shopping.wait_idle()
    assert connector.asked("lista") == ["camisas"]  # solo las categorías elegidas
    state = client.get("/api/shop/state").json()
    assert state["running"] is False and state["pending"] == 1
    assert state["stores"][0]["status"]["state"] == "ok" and state["stores"][0]["status"]["added"] == 1
    assert state["stores"][0]["next_check"]


def test_me_gusta_y_no_me_gusta(client, tienda, photo_bytes):
    _garment(client, photo_bytes, name="Vaquero azul", type="vaquero", color_primary={"name": "azul", "hex": "#2f5fa8"})
    tienda(camisas=[product("a", price=3995), product("b"), product("c")])
    _refresh()

    first = client.get("/api/shop/next").json()
    assert first["remaining"] == 3
    item = first["item"]
    assert item["store_name"] == "Zara" and item["url"].startswith("https://tienda.test/")
    assert item["reasons"] and {"text", "kind"} == set(item["reasons"][0])
    assert client.get(item["photos"][0]["url"]).status_code == 200

    after_like = client.post(f"/api/shop/items/{item['id']}/like").json()
    assert after_like["remaining"] == 2 and after_like["item"]["id"] != item["id"]
    assert client.post(f"/api/shop/items/{item['id']}/like").status_code == 200  # doble toque
    assert client.post(f"/api/shop/items/{item['id']}/dislike").status_code == 409

    disliked = after_like["item"]
    after_dislike = client.post(f"/api/shop/items/{disliked['id']}/dislike").json()
    assert after_dislike["remaining"] == 1
    assert client.get(disliked["photos"][0]["url"]).status_code == 404  # lo descartado no ocupa disco

    liked = client.get("/api/shop/liked").json()
    assert [i["id"] for i in liked] == [item["id"]]
    assert liked[0]["status"] == "gustado" and liked[0]["expires_soon"] is False and liked[0]["expires_at"]
    state = client.get("/api/shop/state").json()
    assert (state["pending"], state["liked"]) == (1, 1)

    # Quitar de «Me gustan»: pasa a descartado y no vuelve.
    assert client.delete(f"/api/shop/items/{item['id']}").status_code == 204
    assert client.get("/api/shop/liked").json() == []
    assert {i.status for i in _items() if i.id in (item["id"], disliked["id"])} == {"descartado"}
    assert client.post("/api/shop/items/999/like").status_code == 404


def test_la_he_comprado_analiza_las_fotos_y_crea_la_prenda(client, tienda, analyzers):
    tienda(camisas=[product("a", "sobrecamisa", "negro")])
    _refresh()
    item = client.get("/api/shop/next").json()["item"]
    client.post(f"/api/shop/items/{item['id']}/like")
    codex, _ = analyzers(FakeAnalyzer("codex", json.dumps(VALID_DRAFT)), FakeAnalyzer("claude"))

    assert client.post(f"/api/shop/items/{item['id']}/bought", json={"size": "L"}).status_code == 409  # sin stock
    bought = client.post(f"/api/shop/items/{item['id']}/bought", json={"size": "M"})
    assert bought.status_code == 200 and bought.json()["analyzed"] is True
    assert codex.calls == 1 and len(codex.images) == 2  # las dos fotos guardadas de la tienda

    garment = client.get(f"/api/garments/{bought.json()['garment_id']}").json()
    assert garment["name"] == "Bomber negra" and garment["ai_provider"] == "codex"  # lo que dijo la IA
    assert (garment["brand"], garment["size"]) == ("Zara", "M")
    assert garment["photo_front"]["id"] == item["photos"][0]["id"]  # las mismas fotos, ahora de la prenda
    assert garment["photo_back"]["id"] == item["photos"][1]["id"]
    assert client.get(garment["photo_front"]["url"]).status_code == 200

    saved = _items()[0]
    assert saved.status == "comprado" and saved.garment_id == garment["id"] and saved.photos == []
    assert saved.ai_draft["name"] == "Bomber negra"
    assert client.get("/api/shop/liked").json() == []
    # Doble toque: no crea otra prenda.
    again = client.post(f"/api/shop/items/{item['id']}/bought", json={"size": "M"})
    assert again.json()["garment_id"] == garment["id"] and len(client.get("/api/garments").json()) == 1
    assert codex.calls == 1

    # Al borrar la prenda se van sus fotos, como con cualquier otra.
    assert client.delete(f"/api/garments/{garment['id']}").status_code == 204
    assert not storage.exists(garment["photo_front"]["id"])


def test_la_he_comprado_con_la_ia_caida_crea_la_prenda_con_lo_estimado(client, tienda, analyzers):
    tienda(camisas=[product("z", "zapatillas", "blanco", name="Zapatilla retro")])
    _refresh()
    item = client.get("/api/shop/next").json()["item"]
    client.post(f"/api/shop/items/{item['id']}/like")
    codex, claude = analyzers(
        FakeAnalyzer("codex", error=AnalysisError("caído")), FakeAnalyzer("claude", is_available=False)
    )

    bought = client.post(f"/api/shop/items/{item['id']}/bought", json={"size": "M"})
    assert bought.status_code == 200 and bought.json()["analyzed"] is False
    assert "zapatillas o zapatos" in codex.prompt  # el calzado se analiza como calzado

    garment = client.get(f"/api/garments/{bought.json()['garment_id']}").json()
    assert (garment["name"], garment["type"], garment["category"]) == ("Zapatilla retro", "zapatillas", "calzado")
    assert garment["color_primary"] == {"name": "blanco", "hex": "#101010"}  # el tono que dio la tienda
    assert (garment["pattern"], garment["style"], garment["season"]) == ("liso", "casual", "todo_el_ano")
    assert (garment["brand"], garment["size"], garment["ai_provider"]) == ("Zara", "M", None)
    assert _items()[0].status == "comprado"


def test_zara_baja_de_pagina_si_la_categoria_tiene_menos(monkeypatch):
    """Pedir más páginas de las que hay da 404: se reintenta con menos en vez de dar la categoría por perdida."""
    from app.services.shops import zara

    connector = zara.ZaraConnector(pause=0, pages=3)
    asked = []

    def fake_json(url, *args, **kwargs):
        asked.append(url)
        return None if "page=3" in url else {"productGroups": []}

    monkeypatch.setattr(connector, "_json", fake_json)
    assert connector.list_category("hombre-camisetas-l855") == []
    assert len(asked) == 2 and asked[1].endswith("page=2")
