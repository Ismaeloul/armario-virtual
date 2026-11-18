"""Las cinco últimas tiendas (18-11-2026): Uniqlo, Mango, H&M, COS y Weekday, de Francia y de hombre. Se leen
con navegador y solo por su listado: se escucha lo que pide la página (o se lee el JSON que trae) y la ficha
NO se abre nunca. Todo sin red ni navegador: fragmentos reales recortados en la investigación (algunos
salieron de la API llamada a pelo durante la investigación: valen igual como muestra de la forma del JSON) y
una sesión de navegador falsa."""
import copy
import json

import pytest
from conftest import VALID_DRAFT, FakeAnalyzer
from sqlalchemy import select
from test_shop import FIXTURES, _items, _refresh
from test_shop_navegador import sin_navegador  # noqa: F401  (fixture)

from app import config
from app.db import SessionLocal
from app.models import ShopItem
from app.services import shopping, shops
from app.services.shops import NeedsBrowser, NotThisStore, SearchError, browser, cos, crawl, hm, listing, mango
from app.services.shops import uniqlo, weekday
from app.services.shops.browser import Response

ULTIMAS = ("uniqlo", "mango", "hm", "cos", "weekday")


def _json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeSession:
    """El navegador de mentira de estas cinco: abrir una página (y oír lo que pide), «ver más» (pulsar su botón
    o bajar hasta el final), leer el JSON que trae la página y leer algo de la página abierta. Nada más: pedir
    a la tienda por nuestra cuenta (`fetch_json`, `fetch_text`) haría saltar el test."""

    def __init__(self, opened=None, more=None, pages=None, flight=""):
        self.opened = opened or {}  # trozo de la dirección -> [Response]
        self.more_answers = list(more or [])  # una lista de [Response] por cada «ver más»
        self.pages = pages or {}  # número de página -> (estado, __NEXT_DATA__)
        self.flight = flight
        self.asked: list[str] = []
        self.clicks: list[str | None] = []

    def open(self, store, url, want, ready, wait=30):
        self.asked.append(url)
        found = next((r for part, r in self.opened.items() if part in url), [])
        return [r for r in found if want(r.url)]

    def more(self, store, want, ready, click=None, wait=30):
        self.clicks.append(click)
        found = self.more_answers.pop(0) if self.more_answers else []
        return [r for r in found if want(r.url)]

    def page_json(self, store, url, script_id="__NEXT_DATA__", wait=10):
        self.asked.append(url)
        return self.pages(url) if callable(self.pages) else (404, None)

    def evaluate(self, store, expression, arg=None):
        return self.flight

    def fetch_json(self, store, url):
        raise AssertionError(f"Se ha llamado a la tienda por nuestra cuenta: {url}")

    fetch_text = fetch_json

    def host(self):
        return ""


def _session(monkeypatch, session: FakeSession) -> FakeSession:
    monkeypatch.setattr(browser, "require", lambda store: session)
    monkeypatch.setattr(browser, "active", lambda: True)
    return session


def _hm_next(listing: dict) -> dict:
    """Un `__NEXT_DATA__` de H&M con ese `productListingData` dentro."""
    return {"props": {"pageProps": {"plpProps": {"productListingSectionProps": {"productListingData": listing}}}}}


# ---------- H&M


def test_hm_lee_el_listado_con_la_foto_sin_modelo_y_sin_tallas():
    products, raw, pages = hm.parse_listing(_hm_next(_json("hm_baskets.json")), "baskets")
    assert raw == 2
    assert [(p.product_ref, p.name, p.type, p.store_color, p.color, p.brand) for p in products] == [
        ("hm:1338515005", "Sneakers", "zapatillas", "Bordeaux", "burdeos", ""),
        ("hm:1359411001", "Chunky trainers", "zapatillas", "Noir", "negro", ""),
    ]
    first = products[0]
    assert first.url == "https://www2.hm.com/fr_fr/productpage.1338515005.html"
    assert hm.HMConnector().reference(first.store_data) == "1338515005"
    detail = hm.HMConnector().cached_detail(first.store_data)
    # La foto de producto (DescriptiveStillLife), de su CDN y con su tamaño; ninguna con modelo.
    assert detail.photo_urls[0] == ("https://image.hm.com/assets/hm/3d/d1/3dd135668f4f4ca3891006d67d239efca7814664.jpg"
                                    "?imwidth=1280")
    # Sin tallas: no se sabe qué queda, y cuenta como disponible.
    assert detail.sizes == [] and detail.stock_known is False and detail.in_stock is True
    assert detail.composition == ""


def test_hm_quita_lotes_y_ropa_de_casa_y_arregla_los_textos_mal_codificados():
    # Las tres de la muestra de camisetas: dos conjuntos de estar en casa y un lote de tres.
    products, raw, _pages = hm.parse_listing(_hm_next(_json("hm_listado.json")), "t-shirts")
    assert raw == 3 and products == []
    data = _json("hm_listado.json")
    tee = data["rawProductList"][0]
    tee["productName"] = "T-shirt Regular Fit en jersey cÃ´telÃ©"  # visto así en sus textos
    products, _raw, _pages = hm.parse_listing(data, "t-shirts")
    assert [(p.name, p.type, p.color, p.price_cents) for p in products] == [
        ("T-shirt Regular Fit en jersey côtelé", "camiseta", "gris", 3499)]
    detail = shops.cached_detail("hm", products[0].store_data)
    # Sus otros colores, con su tono, como productos aparte (el propio incluido).
    assert [(s["product_ref"], s["name"], s["hex"]) for s in detail.siblings] == [
        ("hm:1357440002", "Gris clair chiné", "#afafaf"), ("hm:1357440003", "Bordeaux", "#3a1a19"),
        ("hm:1357440001", "Noir", "#272627"),
    ]
    assert listing.fix_text("intÃ©rieur") == "intérieur" and listing.fix_text("Été") == "Été"


def test_hm_lee_por_defecto_solo_las_primeras_paginas_de_cada_seccion(monkeypatch):
    assert config.shop_limit("hm", "PAGES") == 8 and config.shop_limit("cos", "PAGES") == config.SHOP_MAX_PAGES
    base = _json("hm_baskets.json")
    base["pagination"]["totalPages"] = 35

    def page(url):
        number = int(url.split("page=")[1]) if "page=" in url else 1
        data = copy.deepcopy(base)
        for raw in data["rawProductList"]:
            raw["id"] = f"{raw['id'][:-3]}{number:03d}"
        return 200, _hm_next(data)

    session = _session(monkeypatch, FakeSession(pages=page))
    found = hm.HMConnector().list_category("baskets")
    assert len(found) == 16 and len(session.asked) == 8
    assert session.asked[0] == "https://www2.hm.com/fr_fr/homme/chaussures/baskets.html?sort=newProduct"
    assert session.asked[-1] == "https://www2.hm.com/fr_fr/homme/chaussures/baskets.html?sort=newProduct&page=8"
    # El tope se cambia por tienda.
    monkeypatch.setenv("ARMARIO_SHOP_MAX_PAGES_HM", "3")
    session.asked.clear()
    assert len(hm.HMConnector().list_category("baskets")) == 6 and len(session.asked) == 3


def test_hm_un_fallo_a_mitad_guarda_lo_leido(monkeypatch):
    def page(url):
        if "page=2" in url:
            return 503, None
        data = _json("hm_baskets.json")
        data["pagination"]["totalPages"] = 5
        return 200, _hm_next(data)

    _session(monkeypatch, FakeSession(pages=page))
    with pytest.raises(crawl.Partial) as partial:
        hm.HMConnector().list_category("baskets")
    assert len(partial.value.products) == 2 and "HTTP 503" in str(partial.value)


# ---------- Weekday


def test_weekday_trae_tallas_con_stock_colores_con_tono_y_foto_sin_modelo(monkeypatch):
    data = _json("weekday_listado.json")
    products, raw, pages = weekday.parse_listing(data, "shirts")
    assert raw == 3 and pages == 1
    assert [(p.product_ref, p.name, p.type, p.store_color, p.price_cents, p.pattern) for p in products] == [
        ("weekday:1330797003", "Chemise carrée décontractée en popeline", "camisa", "Carreaux taupe clair", 4999,
         "cuadros"),
        ("weekday:1363332001", "Chemise boxy décontractée en popeline", "camisa", "Blanc", 5499, "liso"),
        ("weekday:1355567001", "Chemise boutonnée en coton-viscose", "camisa", "Blanc rayé", 5999, "rayas"),
    ]
    first = products[0]
    assert first.url == ("https://www.weekday.com/fr-fr/p/men/shirts/long-sleeve-shirts/"
                         "relaxed-boxy-poplin-shirt-checked-light-mole-1330797003")
    detail = weekday.WeekdayConnector().cached_detail(first.store_data)
    assert [s["name"] for s in detail.sizes] == ["XS", "S", "M", "L", "XL"] and detail.stock_known
    assert len(detail.photo_urls) == 1 and "d160422b3d38" in detail.photo_urls[0]  # la StillLife, no la de modelo
    assert [(s["product_ref"], s["hex"]) for s in detail.siblings] == [
        ("weekday:1330797003", "#f5f5dc"), ("weekday:1330797004", "#ffffff"), ("weekday:1330797005", "#0000ff")]
    # Todas las tallas agotadas: no se propone (y un «me gusta» así caduca).
    sold = copy.deepcopy(data)
    for size in sold["products"][0]["sizeVariants"]:
        size["inStock"] = "no"
    gone = weekday.parse_listing(sold, "shirts")[0][0]
    assert shops.cached_detail("weekday", gone.store_data).in_stock is False

    # La sección entera, `?page=N` en el `__NEXT_DATA__` de cada página, hasta la última.
    def page(url):
        listing = copy.deepcopy(data)
        listing["pagination"] = {"limit": 3, "offset": 0, "totalProducts": 5}
        if "page=2" in url:
            listing["products"] = listing["products"][:2]
            for product in listing["products"]:
                product["sku"] = product["sku"][:-1] + "9"
        return 200, {"props": {"pageProps": {"blocks": [{"component": "header"},
                                                        {"component": "product-listing", "listingPageData": listing}]}}}

    session = _session(monkeypatch, FakeSession(pages=page))
    assert len(weekday.WeekdayConnector().list_category("shirts")) == 5
    assert session.asked == ["https://www.weekday.com/fr-fr/men/shirts/", "https://www.weekday.com/fr-fr/men/shirts/?page=2"]


# ---------- COS


def test_cos_lee_el_color_en_frances_y_sale_sin_tallas_ni_composicion():
    products, raw, total = cos.parse_listing(_json("cos_listado.json"), "shirts")
    assert raw == 3 and total == 205
    assert [(p.product_ref, p.name, p.store_color, p.color, p.price_cents) for p in products] == [
        ("cos:26138", "Chemise décontractée laine mélangée", "Bleu marine chiné", "azul marino", 12900),
        ("cos:24548", "Chemise rayée décontractée", "Bleu / rayé", "azul", 6900),
        ("cos:26105", "Chemise en jersey interlock fluide", "Bleu marine", "azul marino", 8900),
    ]
    first = products[0]
    assert first.url == ("https://www.cos.com/fr-fr/men/menswear/shirts/casualshirts/product/"
                         "relaxed-wool-blend-shirt-navy-mlange-1343689003")
    assert cos.COSConnector().reference(first.store_data) == "1343689003"
    detail = shops.cached_detail("cos", first.store_data)
    # Lo que el listado llama `composition` son solo los materiales certificados («30% laine RWS, 30% alpaga
    # RAS» en una docena de camisas distintas): no se enseña como composición.
    assert detail.composition == ""
    assert detail.sizes == [] and not detail.stock_known and detail.in_stock
    assert len(detail.photo_urls) == 1 and "fb921adb462e" in detail.photo_urls[0]
    assert [(s["product_ref"], s["name"]) for s in detail.siblings] == [
        ("cos:26138", "BLEU MARINE CHINÉ"), ("cos:24981", "BRUN CHINÉ")]


def test_cos_escucha_lo_que_pide_la_pagina_y_pulsa_su_boton_de_la_pagina_siguiente(monkeypatch):
    def answer(offset: int, total: int) -> Response:
        data = copy.deepcopy(_json("cos_listado.json"))
        data["data"]["pagination"].update(offset=offset, limit=3, totalProducts=total)
        for product in data["data"]["products"]:
            product["id"] = int(f"{product['id']}{offset}")
            product["attributes"]["articleSwatches"] = []
        url = ("https://api.cos.com/product-search/v1/fr/products?categories=men%2Fmenswear%2Fshirts"
               f"&limit=3&offset={offset}&languageCode=fr")
        return Response(url, 200, data)

    session = _session(monkeypatch, FakeSession(
        opened={"/fr-fr/men/shirts": [answer(0, 7), Response("https://www.cos.com/api/checkout/selection", 403, None)]},
        more=[[answer(3, 7)], [answer(6, 7)]],
    ))
    found = cos.COSConnector().list_category("shirts")
    assert len(found) == 9
    assert session.asked == ["https://www.cos.com/fr-fr/men/shirts"]
    assert session.clicks == [cos.NEXT_BUTTON, cos.NEXT_BUTTON]  # el botón de la web, una vez por página


# ---------- Uniqlo


def test_uniqlo_solo_propone_los_colores_con_foto_sin_modelo(monkeypatch):
    data = _json("uniqlo_listado.json")
    products, raw, total = uniqlo.parse_listing(data, "t-shirts")
    assert raw == 3 and total == 23
    # Del primero, solo el rosa (12) y el gris (06) tienen foto de producto; los otros dos, ninguno.
    assert [(p.product_ref, p.name, p.store_color, p.color, p.price_cents) for p in products] == [
        ("uniqlo:E465193-000-00-06", "T-shirt AIRism en coton (Manches longues)", "Gris", "gris", 2490),
        ("uniqlo:E465193-000-00-12", "T-shirt AIRism en coton (Manches longues)", "Rose", "rosa", 2490),
    ]
    first = products[1]
    assert first.url == "https://www.uniqlo.com/fr/fr/products/E465193-000/00?colorDisplayCode=12"
    assert uniqlo.UniqloConnector().reference(first.store_data) == "465193"
    detail = shops.cached_detail("uniqlo", first.store_data)
    assert all("/WesternCommon/" in url and "goods_12_" in url for url in detail.photo_urls)
    assert detail.sizes == [] and not detail.stock_known
    assert [s["product_ref"] for s in detail.siblings] == ["uniqlo:E465193-000-00-06", "uniqlo:E465193-000-00-12"]

    # La página y lo que pide al abrirla; después, bajando, la siguiente tanda.
    api = "https://www.uniqlo.com/fr/api/commerce/v5/fr/products?path=37609%2C84995%2C85071&offset={}&limit=3"
    second = copy.deepcopy(data)
    second["result"]["items"] = second["result"]["items"][:1]
    second["result"]["items"][0]["productId"] = "E999999-000"
    other = "https://www.uniqlo.com/fr/api/commerce/v5/fr/products?path=37609%2C84995%2C85072&offset=0"
    session = _session(monkeypatch, FakeSession(
        opened={"/men/tops/t-shirts": [Response(api.format(0), 200, data), Response(other, 200, second)]},
        more=[[Response(api.format(3), 200, second)], []],
    ))
    found = uniqlo.UniqloConnector().list_category("t-shirts")
    assert [p.product_ref for p in found] == [
        "uniqlo:E465193-000-00-06", "uniqlo:E465193-000-00-12", "uniqlo:E999999-000-00-06",
        "uniqlo:E999999-000-00-12"]
    assert session.asked == ["https://www.uniqlo.com/fr/fr/men/tops/t-shirts"] and session.clicks == [None, None]


# ---------- Mango


def test_mango_lee_las_tarjetas_de_la_pagina_y_lo_que_pide_al_bajar(monkeypatch):
    flight = (FIXTURES / "mango_flight.txt").read_text(encoding="utf-8")
    cards, prices = mango.parse_cards(flight)
    assert sorted(cards) == ["47071408", "47091487"] and prices["47071408"]["30"]["default"]["price"] == 49.99

    product, product_prices = _json("mango_producto.json"), _json("mango_precios.json")
    found = mango.parse_products({"47041489": product}, {"47041489": product_prices}, "chemises")
    assert [(p.product_ref, p.name, p.store_color, p.color, p.price_cents) for p in found] == [
        ("mango:47041489-56", "Chemise slim fit en coton gratté", "Bleu marine", "azul marino", 4999),
        ("mango:47041489-48", "Chemise slim fit en coton gratté", "Vert forêt", "verde", 4999),
        ("mango:47041489-30", "Chemise slim fit en coton gratté", "Marron", "marrón", 4999),
    ]
    first = found[0]
    assert first.url == "https://shop.mango.com/fr/fr/p/homme/chemises/a-carreaux/chemise-slim-fit-en-coton-gratte/47041489?c=56"
    detail = shops.cached_detail("mango", first.store_data)
    # Solo el bodegón (vista B, «-900»): ni la delantera ni la trasera con modelo.
    assert detail.photo_urls == ["https://media.mango.com/is/image/punto/47041489-56-900?wid=1280"]
    assert detail.color_hex == "#333840" and detail.sizes == [] and not detail.stock_known
    assert mango.MangoConnector().reference(first.store_data) == "47041489"
    # Sin precio de ese color, no se propone.
    assert mango.parse_products({"47041489": product}, {}, "chemises") == []

    orchestrator = "https://online-orchestrator.mango.com/v4/{}?channelId=shop&countryIso=FR&productId=47041489"
    session = _session(monkeypatch, FakeSession(
        opened={"/c/homme/chemises/": [Response(orchestrator.format("prices/products").replace("47041489", "47071408"),
                                                200, prices["47071408"])]},
        more=[[Response(orchestrator.format("products"), 200, product),
               Response(orchestrator.format("prices/products"), 200, product_prices)], []],
        flight=flight,
    ))
    listed = mango.MangoConnector().list_category("chemises")
    refs = {p.product_ref for p in listed}
    assert {"mango:47041489-56", "mango:47071408-30"} <= refs
    assert session.asked == ["https://shop.mango.com/fr/fr/c/homme/chemises/85ceefeb"] and session.clicks == [None, None]


def test_mango_sin_tarjetas_dentro_sigue_bajando_y_sin_nada_lo_dice(monkeypatch):
    # Visto el 18-11-2026 en la única visita real: la página cargó (sin bloqueo) y no se leyó ninguna tarjeta
    # de dentro. Ahora se sigue bajando y se cogen las que pide la página.
    product, product_prices = _json("mango_producto.json"), _json("mango_precios.json")
    orchestrator = "https://online-orchestrator.mango.com/v4/{}?channelId=shop&countryIso=FR&productId=47041489"
    _session(monkeypatch, FakeSession(more=[[Response(orchestrator.format("products"), 200, product),
                                             Response(orchestrator.format("prices/products"), 200, product_prices)]]))
    assert len(mango.MangoConnector().list_category("chemises")) == 3
    _session(monkeypatch, FakeSession())
    with pytest.raises(shops.ShopError, match="sin productos"):
        mango.MangoConnector().list_category("chemises")


# ---------- Lo común: nunca abren una ficha, sin buscador, y las fotos de su CDN


def test_ninguna_abre_la_ficha_ni_busca(monkeypatch):
    monkeypatch.setattr(browser, "active", lambda: True)
    product = hm.parse_listing(_hm_next(_json("hm_baskets.json")), "baskets")[0][0]
    for key in ULTIMAS:
        connector = shops.CONNECTORS[key]
        assert connector.needs_browser and connector.heavy and connector.prepared_colors and connector.language == "fr"
        with pytest.raises(NeedsBrowser):
            connector.detail({"id": "123"})  # sin lo que guardó el listado no hay ficha: no se abre la de la tienda
        with pytest.raises(NotThisStore):
            connector.search("https://www.zara.com/fr/fr/x-p1.html")
    assert shops.CONNECTORS["hm"].detail(product.store_data).photo_urls  # con ello, la de siempre
    for key, link in (("hm", "https://www2.hm.com/fr_fr/productpage.1338515005.html"),
                      ("cos", "https://www.cos.com/fr-fr/men/x/product/y-1343689003"),
                      ("weekday", "https://www.weekday.com/fr-fr/p/men/x-1330797003"),
                      ("uniqlo", "https://www.uniqlo.com/fr/fr/products/E465193-000/00"),
                      ("mango", "https://shop.mango.com/fr/fr/p/homme/x/47041489")):
        with pytest.raises(SearchError) as error:
            shops.CONNECTORS[key].search(link)
        assert not isinstance(error.value, NotThisStore) and "navegador" in str(error.value)


def test_las_cinco_nacen_desactivadas_con_su_dia_y_su_clase_de_ropa(client):
    stores = {s["key"]: s for s in client.get("/api/shop/state").json()["stores"]}
    for key in ULTIMAS:
        assert stores[key]["enabled"] is False and stores[key]["next_check"] is None
        assert stores[key]["browser"] is True and stores[key]["heavy"] is True
    assert [stores[k]["weekday"] for k in ULTIMAS] == [0, 1, 3, 5, 6]
    assert "calzado" in stores["hm"]["kinds"] and "calzado" not in stores["weekday"]["kinds"]
    assert "capa_exterior" in stores["uniqlo"]["kinds"]


# ---------- Sin tallas, de punta a punta: propuesta, me gusta y comprar sin talla


@pytest.fixture
def hm_falsa(monkeypatch, photo_bytes):
    """H&M de verdad, pero con su listado sacado de la muestra y las fotos de mentira."""
    connector = shops.CONNECTORS["hm"]
    listed = {"baskets": hm.parse_listing(_hm_next(_json("hm_baskets.json")), "baskets")[0]}
    monkeypatch.setattr(connector, "list_category", lambda slug: list(listed.get(slug, [])))
    monkeypatch.setattr(connector, "download", lambda url: photo_bytes)
    monkeypatch.setattr(shops.browser, "missing", lambda: None)
    with SessionLocal() as db:
        shopping.set_store(db, "hm", True, ["baskets"])
    return listed


def test_sin_tallas_se_propone_se_guarda_y_se_compra_sin_talla_o_con_una_escrita(client, hm_falsa, analyzers):
    _refresh(stores=["hm"])
    new = _items("nuevo")
    assert {i.product_ref for i in new} == {"hm:1338515005", "hm:1359411001"}
    assert all(i.sizes == [] and i.in_stock and i.photos for i in new)
    shown = client.get("/api/shop/next", params={"store": "hm"}).json()["item"]
    assert shown["sizes"] == [] and shown["reference"] in ("1338515005", "1359411001")
    client.post(f"/api/shop/items/{shown['id']}/like")

    # La semana siguiente sale en el listado: sin dato de stock, no caduca.
    _refresh(stores=["hm"])
    # Y la otra ya no sale (H&M solo se lee en parte): tampoco caduca, sale de lo guardado.
    hm_falsa["baskets"] = [p for p in hm_falsa["baskets"] if p.product_ref != shown["product_ref"]]
    _refresh(stores=["hm"])
    liked = client.get("/api/shop/liked").json()
    assert [i["id"] for i in liked] == [shown["id"]] and liked[0]["sizes"] == []

    analyzers(FakeAnalyzer("codex", json.dumps(VALID_DRAFT)), FakeAnalyzer("claude"))
    bought = client.post(f"/api/shop/items/{shown['id']}/bought", json={"size": None})
    assert bought.status_code == 200
    garment = client.get(f"/api/garments/{bought.json()['garment_id']}").json()
    assert garment["size"] is None and garment["store_name"] == "H&M"

    other = next(i for i in _items("nuevo"))
    written = client.post(f"/api/shop/items/{other.id}/bought", json={"size": " 44 "})
    assert written.status_code == 200
    assert client.get(f"/api/garments/{written.json()['garment_id']}").json()["size"] == "44"


def test_un_color_de_estas_tiendas_solo_se_elige_si_ya_esta_preparado(client, monkeypatch, photo_bytes):
    # Weekday: el listado da tres colores; solo los que salieron en él (y tienen sus fotos) se pueden ver.
    connector = shops.CONNECTORS["weekday"]
    products = weekday.parse_listing(_json("weekday_listado.json"), "shirts")[0]
    monkeypatch.setattr(connector, "list_category", lambda slug: products if slug == "shirts" else [])
    monkeypatch.setattr(connector, "download", lambda url: photo_bytes)
    monkeypatch.setattr(shops.browser, "missing", lambda: None)
    with SessionLocal() as db:
        shopping.set_store(db, "weekday", True, ["shirts"])
    _refresh(stores=["weekday"])
    with SessionLocal() as db:
        item = db.scalars(select(ShopItem).where(ShopItem.product_ref == "weekday:1330797003")).one()
        colors = shopping.colors_of(item)
        assert [c["available"] for c in colors] == [True, False, False]  # los otros dos no salieron en el listado
    answer = client.post(f"/api/shop/items/{item.id}/color", json={"product_ref": "weekday:1330797004"})
    assert answer.status_code == 503 and "tienda" in answer.json()["detail"]

