"""Pull&Bear y Bershka: las tiendas que se leen con un navegador de verdad. Todo sin red ni navegador:
respuestas JSON reales recortadas (capturadas el 18-11-2026) y una sesión de navegador falsa."""
import json
import time
from datetime import timedelta

import pytest
from conftest import FakeAnalyzer  # noqa: F401  (mismo patrón que los otros tests de Compras)
from test_shop import FIXTURES, INVIERNO, _items, _refresh, product, tienda  # noqa: F401  (fixture)
from test_shop_francia import FakeTranslator

from app.db import SessionLocal
from app.models import ShopItem, now_utc
from app.services import shopping, shops
from app.services.ai import translate as traductor
from app.services.shops import BlockedError, BrowserUnavailable, NotThisStore, SearchError, ShopError
from app.services.shops import bershka, browser, inditex, pullandbear


def _json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def sin_navegador(monkeypatch):
    """Ningún test abre Chromium: si algo lo intenta, falla. Y cada test empieza sin bloqueos."""

    def _no(self):
        raise AssertionError("Un test ha intentado abrir el navegador")

    monkeypatch.setattr(browser.Session, "_launch", _no)
    browser.forget_blocks()
    yield
    browser.forget_blocks()


class FakeSession:
    """Lo que el conector le pide al navegador: abrir una página (y oír su JSON) y pedir desde dentro."""

    def __init__(self, responses=None, fetched=None, host=""):
        self.responses = responses or []
        self.fetched = fetched or {}  # trozo de la dirección -> (estado, JSON)
        self.opened: list[str] = []
        self.asked: list[str] = []
        self._host = host

    def host(self):
        return self._host

    def open(self, store, url, want, ready, wait=30):
        self.opened.append(url)
        self._host = url
        return [r for r in self.responses if want(r.url)]

    def fetch_json(self, store, url):
        self.asked.append(url)
        for part, answer in self.fetched.items():
            if part in url:
                if isinstance(answer, Exception):
                    raise answer
                return answer
        return 404, None


def _con_sesion(monkeypatch, session):
    monkeypatch.setattr(inditex.browser, "require", lambda store: session)
    monkeypatch.setattr(inditex.browser, "active", lambda: True)


PB_CATEGORY = "https://www.pullandbear.com/itxrest/3/catalog/store/24009401/20309459/category/1030204823/product?languageId=-2&showProducts=false&priceFilter=true&appId=1"
PB_ARRAY = "https://www.pullandbear.com/itxrest/3/catalog/store/24009401/20309459/productsArray?languageId=-2&productIds=773993626%2C775846918&appId=1"


# ---------- Lo que se lee del JSON


def test_pull_and_bear_lee_sus_fichas_sin_repetir_y_con_fotos_sin_modelo():
    products = inditex.parse_products(_json("pullandbear_sweats.json")["products"], pullandbear.SITE, "sweats-n6382")
    # Cuatro «bundles», pero dos son el mismo producto en el mismo color: tres productos.
    assert [(p.product_ref, p.name, p.store_color, p.color, p.type, p.price_cents) for p in products] == [
        ("pullandbear:773992767-803", "Sweat capuche Subaru", "Gris vigoré", "gris", "sudadera", 3999),
        ("pullandbear:773993320-422", "Sweat capuche Subaru", "Bleu marine sombre", "azul marino", "sudadera", 3999),
        ("pullandbear:763994346-401", "Sweat à capuche STWD", "Bleu marine", "azul marino", "sudadera", 3599),
    ]
    first = products[0]
    assert first.url == "https://www.pullandbear.com/fr/sweat-capuche-subaru-l03501500?cS=803&pelement=773993626"
    assert first.season == "invierno" and first.category == "parte_superior"
    assert inditex.reference(first.store_data) == "3501/500/803"
    detail = inditex.detail_from(pullandbear.SITE, first.store_data)
    # Delante (a6m) y detrás (a20m), sin modelo, sacadas de la CDN con su ancho.
    assert [url.split("/")[-1].split("?")[0] for url in detail.photo_urls] == ["03501500803-A6M.jpg", "03501500803-A20M.jpg"]
    assert all(url.startswith("https://static.pullandbear.net/assets/public/") and url.endswith("w=1280")
               for url in detail.photo_urls)
    assert detail.in_stock and detail.sizes[0] == {"name": "XS", "in_stock": True}
    assert detail.composition.startswith("Extérieur: 65% coton, 35% polyester")
    assert detail.store_color == "Gris vigoré" and detail.store_data == {}
    # El de tres colores trae a sus hermanos, cada uno con lo necesario para su ficha sin la tienda.
    siblings = inditex.detail_from(pullandbear.SITE, products[2].store_data).siblings
    assert [s["product_ref"] for s in siblings] == [
        "pullandbear:763994346-401", "pullandbear:763994346-501", "pullandbear:763994346-805",
    ]
    other = inditex.detail_from(pullandbear.SITE, siblings[1]["store_data"])
    assert other.store_color == siblings[1]["name"] and other.photo_urls and other.photo_urls != detail.photo_urls
    assert "cS=501" in siblings[1]["url"]


def test_bershka_lee_ropa_y_calzado_con_sus_vistas():
    products = inditex.parse_products(_json("bershka_sweats.json")["products"], bershka.SITE, "sweats-n3714")
    assert [(p.product_ref, p.store_color, p.color, p.price_cents) for p in products] == [
        ("bershka:226925435-812", "Gris", "gris", 3999), ("bershka:233408678-902", "Rose", "rosa", 2999),
    ]
    assert products[0].url == "https://www.bershka.com/fr/sweat-technique-%C3%A0-capuche-c0p226927200.html?colorId=812"
    detail = inditex.detail_from(bershka.SITE, products[1].store_data)
    assert [u.split("/")[-1].split("?")[0] for u in detail.photo_urls] == ["02434190902-a4o.jpg", "02434190902-b.jpg"]
    assert len(detail.siblings) == 5
    # Calzado: lateral, desde atrás en tres cuartos y desde arriba (no la del modelo sentado).
    shoe = inditex.parse_products(_json("bershka_baskets.json")["products"], bershka.SITE, "baskets-n6125")[0]
    assert (shoe.type, shoe.category, shoe.color) == ("zapatillas", "calzado", "blanco")
    photos = inditex.detail_from(bershka.SITE, shoe.store_data).photo_urls
    assert [u.split("?")[0].rsplit("-", 1)[-1] for u in photos] == ["a4o.jpg", "a3o.jpg", "a5o.jpg"]
    assert [s["name"] for s in inditex.detail_from(bershka.SITE, shoe.store_data).sizes][:2] == ["39", "40"]


def test_si_solo_hay_fotos_con_modelo_se_usa_la_primera_y_se_dice():
    data = _json("bershka_sweats.json")["products"][:1]
    for xmedia in data[0]["bundleProductSummaries"][0]["detail"]["xmedia"]:
        for item in xmedia["xmediaItems"]:
            item["medias"] = [m for m in item["medias"] if m["extraInfo"]["originalName"] not in ("a4o", "s1", "b1")]
    product_ = inditex.parse_products(data, bershka.SITE, "sweats-n3714")[0]
    detail = inditex.detail_from(bershka.SITE, product_.store_data)
    assert len(detail.photo_urls) == 1 and "-r/" not in detail.photo_urls[0]  # la miniatura de relleno no
    assert detail.store_data == {"model_photo": True}


def test_los_ids_de_la_categoria_y_las_direcciones_de_fichas():
    assert inditex.category_ids(_json("pullandbear_categoria.json"))[:3] == ["773993626", "775846918", "773993696"]
    url = inditex.with_ids(PB_ARRAY, ["1", "2"])
    assert "productIds=1,2" in url and "languageId=-2" in url and url.count("productIds") == 1
    assert inditex.array_url(PB_CATEGORY) == (
        "https://www.pullandbear.com/itxrest/3/catalog/store/24009401/20309459/productsArray"
        "?categoryId=1030204823&languageId=-2&appId=1"
    )


# ---------- El conector, con una sesión de navegador falsa


def test_el_listado_oye_el_json_de_la_pagina_y_pide_lo_que_falta(monkeypatch):
    sweats = _json("pullandbear_sweats.json")["products"]
    category = {"sortedProductIds": [773993626, 775846918, 773993696, 763995187]}
    session = FakeSession(
        responses=[
            browser.Response(PB_CATEGORY, 200, category),
            browser.Response(PB_ARRAY, 200, {"products": sweats[:2]}),
            browser.Response("https://www.pullandbear.com/itxrest/2/user/store/24009401/current-user", 201, None),
        ],
        fetched={"productsArray": (200, {"products": sweats[2:]})},
    )
    _con_sesion(monkeypatch, session)
    connector = pullandbear.PullAndBearConnector()
    products = connector.list_category("sweats-n6382")
    assert session.opened == ["https://www.pullandbear.com/fr/homme/vetements/sweats-n6382"]
    # Solo se piden las que la página no trajo, con la misma dirección que usa la web.
    assert len(session.asked) == 1 and "productIds=773993696,763995187" in session.asked[0]
    assert [p.product_ref for p in products] == [
        "pullandbear:773992767-803", "pullandbear:773993320-422", "pullandbear:763994346-401",
    ]
    assert connector.catalog_id == 20309459


def test_sin_el_json_de_la_categoria_es_un_fallo_de_la_tienda(monkeypatch):
    _con_sesion(monkeypatch, FakeSession(responses=[]))
    with pytest.raises(ShopError, match="sin categoría"):
        pullandbear.PullAndBearConnector().list_category("sweats-n6382")


def test_la_ficha_sale_de_la_instantanea_y_si_es_vieja_se_pide_a_la_tienda(monkeypatch):
    connector = bershka.BershkaConnector()
    product_ = inditex.parse_products(_json("bershka_sweats.json")["products"], bershka.SITE, "sweats-n3714")[0]
    data = dict(product_.store_data)
    # Fuera de una consulta (una petición HTTP normal: elegir otro color) no se abre nunca el navegador.
    assert not browser.active()
    assert connector.detail(data).price_cents == 3999
    old = {**data, "snap": {**data["snap"], "at": int(time.time()) - 3 * 24 * 3600}}
    assert connector.detail(old).price_cents == 3999  # vieja, pero es lo que hay
    with pytest.raises(ShopError, match="se lee con navegador"):
        connector.detail({k: v for k, v in data.items() if k != "snap"})
    # Dentro de una consulta, con la instantánea vieja: primero la página del producto y luego su ficha.
    ficha = _json("bershka_ficha.json")
    session = FakeSession(fetched={"/product/226925435/detail": (200, ficha)})
    _con_sesion(monkeypatch, session)
    fresh = connector.detail({**old, "id": "226925435", "color": "250"})
    assert session.opened and session.opened[0].startswith("https://www.bershka.com/fr/")
    assert session.asked == [
        "https://www.bershka.com/itxrest/2/catalog/store/44009501/40259533/category/0/product/226925435/detail"
        "?languageId=-2&appId=1"
    ]
    assert fresh.price_cents == 2599 and fresh.store_color == "Blanc"
    assert fresh.store_data["snap"]["at"] > old["snap"]["at"]  # la nueva se guarda con el item
    # Si la tienda ya no lo tiene: None.
    session.fetched = {"/detail": (404, None)}
    assert connector.detail({**old, "id": "1"}) is None


def test_el_buscador_no_abre_el_navegador_y_lo_explica():
    connector = pullandbear.PullAndBearConnector()
    with pytest.raises(SearchError, match="Pull&Bear solo se lee con navegador"):
        connector.search("https://www.pullandbear.com/fr/sweat-capuche-subaru-l03501500?cS=803", 6)
    with pytest.raises(NotThisStore):
        connector.search("https://www.zara.com/fr/fr/x-p03918300.html", 6)
    with pytest.raises(NotThisStore):
        connector.search("3501/500", 6)


def test_buscar_un_enlace_de_pull_and_bear_responde_con_el_motivo(client):
    response = client.post("/api/shop/lookup", json={"query": "https://www.bershka.com/fr/x-c0p1.html"})
    assert response.status_code == 404 and "Bershka solo se lee con navegador" in response.json()["detail"]


# ---------- El navegador: bloqueos, sin instalar, sin sesión


class FakePage:
    def __init__(self, title="", text="", frames=()):
        self._title, self._text = title, text
        self.frames = [type("F", (), {"url": u})() for u in frames]

    def title(self):
        return self._title

    def inner_text(self, selector, timeout=None):
        return self._text


@pytest.mark.parametrize(
    ("page", "status", "message"),
    [
        (FakePage(title="Access Denied", text="You don't have permission to access"), 200, browser.BLOCKED_TEXT),
        (FakePage(text="Bienvenue " * 400), 403, browser.BLOCKED_TEXT),
        (FakePage(text="x" * 3000, frames=["https://geo.captcha-delivery.com/captcha/?x=1"]), 200, browser.CAPTCHA_TEXT),
        (FakePage(text="Please verify you are human"), 200, browser.CAPTCHA_TEXT),
    ],
)
def test_un_bloqueo_o_un_captcha_paran_con_la_tienda_hasta_manana(page, status, message):
    session = browser.Session()
    with pytest.raises(BlockedError, match=message):
        session._check("bershka", page, status)
    assert browser.blocked("bershka").startswith(message) and "hasta mañana" in browser.blocked("bershka")
    assert browser.blocked("pullandbear") is None
    # Y hoy ya no se le pregunta: `require` falla sin abrir nada.
    with browser.session():
        with pytest.raises(BlockedError):
            browser.require("bershka")


def test_una_pagina_normal_no_es_un_bloqueo():
    browser.Session()._check("bershka", FakePage(title="Sweats homme", text="Sweat capuche " * 300), 200)
    assert browser.blocked("bershka") is None


def test_fuera_de_una_consulta_no_hay_navegador_y_la_sesion_se_cierra_sin_abrirlo(monkeypatch):
    monkeypatch.setattr(browser, "missing", lambda: None)
    with pytest.raises(ShopError, match="segundo plano"):
        browser.require("pullandbear")
    with browser.session() as opened:
        assert browser.active() and browser.require("pullandbear") is opened
    assert not browser.active()  # cerrada sin haber arrancado nada (el test fallaría si lo intentara)


def test_falta_el_navegador_segun_lo_instalado(monkeypatch, tmp_path):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    monkeypatch.setenv("DISPLAY", ":0")
    assert browser.missing() == "No disponible: falta el navegador"
    (tmp_path / "chromium-1255").mkdir()
    assert browser.missing() is None
    monkeypatch.setattr(browser.importlib.util, "find_spec", lambda name: None)
    assert browser.missing() == "No disponible: falta el navegador"


def test_el_navegador_que_no_arranca_se_dice_distinto_y_no_se_reintenta(monkeypatch):
    calls = []

    def launch(self):
        calls.append(1)
        raise BrowserUnavailable(f"{browser.NO_START_TEXT} (Error: Host system is missing dependencies)")

    monkeypatch.setattr(browser.Session, "_launch", launch)
    session = browser.Session()
    for _ in range(2):
        with pytest.raises(BrowserUnavailable, match="no arranca"):
            session._start()
    assert len(calls) == 1  # en la misma consulta no se insiste
    assert "bloqueado" not in browser.NO_START_TEXT


# ---------- Con el resto de la app


@pytest.fixture
def tiendas_de_navegador(monkeypatch, tienda):
    """Pull&Bear de verdad (con su JSON recortado), Zara falsa, y las dos activadas."""
    monkeypatch.setattr(browser, "missing", lambda: None)
    zara_ = tienda(camisas=[product("z1")])
    with SessionLocal() as db:
        shopping.set_store(db, "pullandbear", True, ["sweats-n6382", "pulls-n6378"])
    return zara_


def test_si_falta_el_navegador_la_tienda_sale_no_disponible_y_las_demas_siguen(client, monkeypatch, tienda):
    zara_ = tienda(camisas=[product("z1")])
    monkeypatch.setattr(browser, "missing", lambda: "No disponible: falta el navegador")
    called = []
    monkeypatch.setattr(pullandbear.PullAndBearConnector, "list_category", lambda self, slug: called.append(slug))
    with SessionLocal() as db:
        shopping.set_store(db, "pullandbear", True, None)
    state = {s["key"]: s for s in client.get("/api/shop/state").json()["stores"]}
    assert state["pullandbear"]["unavailable"] == "No disponible: falta el navegador"
    assert state["bershka"]["unavailable"] == "No disponible: falta el navegador" and state["bershka"]["browser"]
    assert state["zara"]["unavailable"] is None and not state["zara"]["browser"]
    result = _refresh(limit=4)
    assert called == []  # ni se intenta
    assert "camisas" in zara_.asked("lista") and result["added"] == 1
    status = client.get("/api/shop/state").json()["stores"]
    pb = next(s for s in status if s["key"] == "pullandbear")["status"]
    assert pb["state"] == "failed" and pb["error"] == "Pull&Bear: No disponible: falta el navegador"


def test_un_bloqueo_para_la_tienda_se_apunta_y_hoy_no_se_insiste(client, monkeypatch, tiendas_de_navegador):
    asked = []

    def blocked_listing(self, slug):
        asked.append(slug)
        raise browser.block("pullandbear", browser.CAPTCHA_TEXT)

    monkeypatch.setattr(pullandbear.PullAndBearConnector, "list_category", blocked_listing)
    result = _refresh(limit=4)
    assert asked == ["sweats-n6382"]  # paró en la primera sección
    assert "camisas" in tiendas_de_navegador.asked("lista") and result["added"] >= 1  # Zara, igual
    pb = next(s for s in client.get("/api/shop/state").json()["stores"] if s["key"] == "pullandbear")["status"]
    assert pb["error"].startswith("Pull&Bear: la tienda pide un captcha") and "hasta mañana" in pb["error"]
    # «Consultar ahora» el mismo día (aunque se reinicie la app): ni se toca la tienda.
    browser.forget_blocks()
    _refresh(limit=4, stores=["pullandbear"])
    assert asked == ["sweats-n6382"]
    with SessionLocal() as db:
        assert shopping.blocked_today(db, "pullandbear", INVIERNO).startswith("la tienda pide un captcha")
        assert not shopping.reachable(db, "pullandbear", INVIERNO)
        # Al día siguiente, sí.
        assert shopping.reachable(db, "pullandbear", INVIERNO + timedelta(days=1))
    _refresh(INVIERNO + timedelta(days=1), limit=4, stores=["pullandbear"])
    assert asked == ["sweats-n6382", "sweats-n6382"]


def test_el_navegador_que_no_arranca_no_es_un_bloqueo(client, monkeypatch, tiendas_de_navegador):
    asked = []

    def broken(self, slug):
        asked.append(slug)
        raise BrowserUnavailable(f"{browser.NO_START_TEXT} (Error: Executable doesn't exist)")

    monkeypatch.setattr(pullandbear.PullAndBearConnector, "list_category", broken)
    _refresh(limit=4)
    assert asked == ["sweats-n6382"]
    pb = next(s for s in client.get("/api/shop/state").json()["stores"] if s["key"] == "pullandbear")["status"]
    assert pb["error"].startswith("Pull&Bear: el navegador no arranca en este equipo") and "bloque" not in pb["error"]
    with SessionLocal() as db:
        assert shopping.blocked_today(db, "pullandbear", INVIERNO) is None  # mañana o con «Consultar ahora», otra vez


def test_una_consulta_de_pull_and_bear_deja_propuestas_con_fotos_y_colores(client, monkeypatch, tiendas_de_navegador,
                                                                            photo_bytes):
    sweats = inditex.parse_products(_json("pullandbear_sweats.json")["products"], pullandbear.SITE, "sweats-n6382")
    monkeypatch.setattr(pullandbear.PullAndBearConnector, "list_category",
                        lambda self, slug: sweats if slug == "sweats-n6382" else [])
    downloaded = []
    monkeypatch.setattr(pullandbear.PullAndBearConnector, "download", lambda self, url: downloaded.append(url) or photo_bytes)
    with browser.session():  # como en el hilo de las consultas
        result = _refresh(limit=8)
    assert result["failed"] == 0
    shown = [i for i in _items("nuevo") if i.store == "pullandbear"]
    assert len(shown) == 3 and all(len(i.photos) == 2 for i in shown)
    assert all("static.pullandbear.net" in url for url in downloaded)
    stwd = next(i for i in shown if i.product_ref == "pullandbear:763994346-401")
    assert stwd.siblings and len(stwd.siblings) == 3
    # Elegir otro color es una petición HTTP normal: sale de la instantánea, sin navegador.
    answer = client.post(f"/api/shop/items/{stwd.id}/color", json={"product_ref": "pullandbear:763994346-501"})
    assert answer.status_code == 200 and answer.json()["product_ref"] == "pullandbear:763994346-501"
    assert answer.json()["reference"] == "7551/528/501" and len(answer.json()["photos"]) == 2


# ---------- El color se enseña en español


def _guardado(**fields) -> int:
    with SessionLocal() as db:
        row = ShopItem(
            store=fields.pop("store", "pullandbear"), product_ref=fields.pop("product_ref", "pullandbear:1-800"),
            name="Sweat", price_cents=2999, url=fields.pop("url", "https://www.pullandbear.com/fr/x"),
            store_color=fields.pop("store_color", "Noir"), section="", type="sudadera", category="parte_superior",
            color=fields.pop("color", "negro"), pattern="liso", style="casual", season="invierno", status="gustado",
            batch=INVIERNO, liked_at=now_utc(), photos=[], **fields,
        )
        db.add(row)
        db.commit()
        return row.id


def test_el_color_sale_traducido_o_en_nuestra_paleta_nunca_en_frances(client):
    siblings = [
        {"product_ref": "pullandbear:1-800", "name": "Noir", "hex": None},
        {"product_ref": "pullandbear:1-250", "name": "Blanc cassé", "hex": None, "name_es": "Blanco roto"},
    ]
    _guardado(siblings=siblings)
    item = client.get("/api/shop/liked").json()[0]
    # Sin traducción todavía: el color de nuestra paleta, no «Noir». Los circulitos, igual.
    assert item["store_color"] == "negro"
    assert [c["name"] for c in item["colors"]] == ["Blanco roto", "negro"]
    with SessionLocal() as db:
        row = db.get(ShopItem, item["id"])
        row.store_color_es = "Negro"
        db.commit()
    assert client.get("/api/shop/liked").json()[0]["store_color"] == "Negro"
    # Una tienda en español (o un producto guardado de la tienda española) se enseña tal cual.
    _guardado(store="zara", product_ref="zara:2-800", url="https://www.zara.com/es/es/x-p1.html", store_color="Marino",
              color="azul marino")
    zara_item = next(i for i in client.get("/api/shop/liked").json() if i["store"] == "zara")
    assert zara_item["store_color"] == "Marino"


def test_los_nombres_de_los_colores_hermanos_se_traducen_en_el_mismo_lote(client, monkeypatch):
    _guardado(siblings=[{"product_ref": "pullandbear:1-800", "name": "Noir", "hex": None},
                        {"product_ref": "pullandbear:1-422", "name": "Bleu marine sombre", "hex": None}])
    fake = FakeTranslator()
    monkeypatch.setattr(traductor, "BACKENDS", [("codex", fake)])
    with SessionLocal() as db:
        assert shopping.translate_items(db) == 1
    assert len(fake.calls) == 1 and "Bleu marine sombre" in fake.calls[0]
    item = client.get("/api/shop/liked").json()[0]
    assert item["store_color"] == "ES: Noir"
    assert sorted(c["name"] for c in item["colors"]) == ["ES: Bleu marine sombre", "ES: Noir"]
    # Al poner al día los colores con la ficha, lo traducido se conserva.
    with SessionLocal() as db:
        row = db.get(ShopItem, item["id"])
        shopping._apply_detail(row, shops.ShopDetail(price_cents=None, sizes=[], photo_urls=[], siblings=[
            {"product_ref": "pullandbear:1-800", "name": "Noir", "hex": None},
            {"product_ref": "pullandbear:1-422", "name": "Bleu marine sombre", "hex": None},
        ]))
        db.commit()
        assert all(s.get("name_es") for s in db.get(ShopItem, item["id"]).siblings)
