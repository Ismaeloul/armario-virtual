"""Las cinco tiendas de la tanda del 18-11-2026 por la tarde (Snipes, size?, Foot Locker, Jules y Bonobo), el
reparto de noches con quince tiendas y la misma zapatilla en varias tiendas. Todo sin red ni navegador: los
fragmentos reales recortados en la investigación y sesiones o clientes falsos."""
import base64
import gzip
import io
import json

import pytest
from PIL import Image
from sqlalchemy import select
from test_shop import FIXTURES, FakeConnector, _items, _refresh, product
from test_shop_navegador import sin_navegador  # noqa: F401  (fixture)

from app import config
from app.db import SessionLocal
from app.models import ShopItem
from app.services import shopping, shops
from app.services.shops import NeedsBrowser, NotThisStore, SearchError, ShopDetail, bonobo, browser, crawl, fetch
from app.services.shops import footlocker, jules, sfra, sizeofficial, snipes
from app.services.shops.browser import Response

NUEVAS = ("snipes", "size", "footlocker", "jules", "bonobo")


def _json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeFetcher:
    """Lo que el conector le pide a la tienda sin navegador: trozo de dirección -> (estado, texto)."""

    def __init__(self, pages: dict):
        self.pages = pages
        self.asked: list[str] = []

    def get(self, url, accept=None, pause=None):
        self.asked.append(url)
        for part, (status, body) in self.pages.items():
            if part in url:
                return fetch.Page(status, body if isinstance(body, bytes) else body.encode("utf-8"))
        return fetch.Page(404, b"")


class FakeBrowser:
    """El navegador de mentira: páginas que se abren (y sus respuestas), HTML de páginas y peticiones desde
    dentro (texto o JSON) y fotos abiertas en otra pestaña."""

    def __init__(self, responses=None, pages=None, texts=None, jsons=None, images=None, host=""):
        self.responses = responses or {}  # trozo de la página -> [Response]
        self.pages = pages or {}  # trozo -> (estado, html)
        self.texts = texts or {}
        self.jsons = jsons or {}
        self.images = images or {}
        self.asked: list[str] = []
        self._host = host

    def host(self):
        return self._host

    def open(self, store, url, want, ready, wait=30):
        self.asked.append(url)
        self._host = url
        for part, found in self.responses.items():
            if part in url:
                return [r for r in found if want(r.url)]
        return []

    def page_html(self, store, url):
        self.asked.append(url)
        self._host = url
        return next((answer for part, answer in self.pages.items() if part in url), (404, None))

    def fetch_text(self, store, url):
        self.asked.append(url)
        return next((answer for part, answer in self.texts.items() if part in url), (404, ""))

    def fetch_json(self, store, url):
        self.asked.append(url)
        return next((answer for part, answer in self.jsons.items() if part in url), (404, None))

    def image(self, store, url):
        self.asked.append(url)
        return next((answer for part, answer in self.images.items() if part in url), b"")


def _browser(monkeypatch, session: FakeBrowser) -> FakeBrowser:
    monkeypatch.setattr(browser, "require", lambda store: session)
    monkeypatch.setattr(browser, "active", lambda: True)
    return session


def _ng_state(body: dict, product_id: str) -> str:
    """Una ficha de Snipes como la pinta su servidor: la respuesta de `products/<id>` en gzip + base64."""
    raw = base64.b64encode(gzip.compress(json.dumps({"url": "x", "status": 200, "body": json.dumps(body)}).encode()))
    state = {f"Product-{product_id}": raw.decode(), "otra-cosa": {"a": 1}}
    return f'<html><body><script id="ng-state" type="application/json">{json.dumps(state)}</script></body></html>'


def _hydration(data: dict) -> str:
    """Una página de Foot Locker como la pinta su servidor (`JSON.parse("…")` con los datos dentro)."""
    return (f"<html><script>window.__staticRouterHydrationData = JSON.parse({json.dumps(json.dumps(data))});"
            "</script></html>")


# ---------- Snipes


def test_snipes_lee_el_listado_que_pide_la_pagina_y_la_ficha_sin_navegador(monkeypatch):
    products = snipes.parse_listing(_json("snipes_listado.json"), "chaussures-77")
    assert [(p.product_ref, p.brand, p.name, p.store_color, p.color, p.price_cents, p.type) for p in products] == [
        ("snipes:141161", "The North Face", "Glenclyffe Urban Low", "Brun", "marrón", 13499, "zapatillas"),
        ("snipes:139044", "The North Face", "Clyffe Ultra", "Noir", "negro", 14999, "zapatillas"),
    ]
    assert products[0].url == "https://www.snipes.com/fr-fr/p/the-north-face-glenclyffe-urban-low-brun-141161"
    # Ropa (una sudadera de adidas) no entra: Snipes es solo zapatillas.
    assert snipes.make_product(_json("snipes_ficha_sudadera.json"), "nouveautes-662") is None

    # El listado: la página de la sección, y lo que ella misma pide a su API (nunca se llama a pelo).
    listing = _json("snipes_listado.json")
    api = "https://api.snipes.com/sni-pl-prd-stor-we-char/v1/v1/categories/77?page=0&perPage=24&sorting=new"
    session = _browser(monkeypatch, FakeBrowser(responses={"chaussures-77": [Response(api, 200, listing)]}))
    listing["pagination"]["totalPages"] = 1
    found = snipes.SnipesConnector().list_category("chaussures-77")
    assert [p.product_ref for p in found] == ["snipes:141161", "snipes:139044"]
    assert session.asked == ["https://www.snipes.com/fr-fr/c/hommes/chaussures-77?page=1&sort=new&sortDir=desc"]

    # La ficha, con una petición normal: el `ng-state` trae el producto en gzip + base64.
    body = _json("snipes_ficha.json")
    connector = snipes.SnipesConnector(pause=0)
    connector.fetcher = FakeFetcher({"/p/nike-air-force-1-07-blanc-1727": (200, _ng_state(body, "1727"))})
    detail = connector.detail({"id": "1727", "url": "https://www.snipes.com/fr-fr/p/nike-air-force-1-07-blanc-1727"})
    # Lateral, tres cuartos, tres cuartos trasera y cenital; ni la suela (_4) ni la de un cliente (_6_UGC).
    assert [u.split("/")[-2] for u in detail.photo_urls] == ["01126425_1", "01126425_2", "01126425_3", "01126425_5"]
    assert not any("UGC" in u for u in detail.photo_urls)
    assert detail.sizes == [{"name": "38.5", "in_stock": False}, {"name": "39", "in_stock": False},
                            {"name": "40", "in_stock": True}]
    assert detail.store_data == {"mpn": "CW2288-111"} and detail.store_color == "Blanc"
    assert detail.composition == "Dessus: cuir · Doublure: textile · Semelle: caoutchouc"
    assert [s["product_ref"] for s in detail.siblings] == ["snipes:1727", "snipes:834"]
    # Referencia y clave: el código de fabricante (el de la caja); sin ficha aún, el de Snipes.
    assert snipes.reference({"mpn": "CW2288-111", "code": "01126425"}) == "CW2288-111"
    assert snipes.reference({"code": "01126425"}) == "01126425"
    assert shops.maker_code("snipes", {"mpn": "CW2288-111"}) == "CW2288111"
    assert snipes.product_state("<html>nada</html>") is None


def test_snipes_busca_por_enlace_y_nada_mas():
    assert snipes.parse_query("https://www.snipes.com/fr-fr/p/nike-air-force-1-07-blanc-1727") == (
        "/p/nike-air-force-1-07-blanc-1727", "1727")
    for otra in ("CW2288-111", "air force", "https://www.zara.com/fr/fr/x.html"):
        with pytest.raises(NotThisStore):
            snipes.parse_query(otra)


# ---------- size?


def test_size_lee_lo_que_pide_la_coleccion_y_la_ficha_en_el_navegador(monkeypatch):
    data = _json("size_listado.json")
    products = sizeofficial.parse_listing(data, "chaussures-hommes")
    assert [(p.product_ref, p.brand, p.name, p.price_cents, p.color) for p in products] == [
        ("size:19774073", "Adidas", "Kegler Super GORE-TEX", 14000, ""),
        ("size:19773942", "HOKA", "Tor Summit Field", 21000, ""),
    ]
    assert products[0].store_data["img"] == "https://cdn.shopify.com/s/files/1/0921/0911/1619/files/sz_806181_a.jpg"

    bloomreach = "https://core.dxpapi.com/api/v1/core/?q=x&start=0&rows=48"
    session = _browser(monkeypatch, FakeBrowser(
        responses={"/collections/chaussures-hommes": [Response(bloomreach, 200, data)]},
        pages={"/products/19774073": (200, _text("size_ficha.html"))},
    ))
    data["response"]["numFound"] = 2
    connector = sizeofficial.SizeConnector()
    assert [p.product_ref for p in connector.list_category("chaussures-hommes")] == ["size:19774073", "size:19773942"]
    detail = connector.detail(products[0].store_data)
    assert session.asked == ["https://www.sizeofficial.fr/collections/chaussures-hommes",
                             "https://www.sizeofficial.fr/products/19774073"]
    # Solo la `_a` (lateral, sin persona), de la CDN de Shopify; el código de fabricante, del final de la descripción.
    assert detail.photo_urls == ["https://cdn.shopify.com/s/files/1/0921/0911/1619/files/sz_806181_a.jpg?width=1600"]
    assert detail.store_data == {"mpn": "LA2249"} and detail.store_color == "Bleu" and detail.price_cents == 14000
    assert detail.sizes[:2] == [{"name": "38", "in_stock": True}, {"name": "38 2/3", "in_stock": True}]
    assert detail.sizes[-1] == {"name": "46", "in_stock": False}
    assert not detail.description.endswith("LA2249")


def test_size_saca_los_otros_colores_de_los_circulitos_y_no_abre_el_navegador_de_dia(monkeypatch):
    detail = sizeofficial.parse_product_page(_text("size_ficha_colores.html"), {})
    assert len(detail.siblings) == 9
    own = next(s for s in detail.siblings if s["product_ref"] == "size:19750826")
    assert own["name"] == "Gris" and own["store_data"]["img"].endswith("_a.jpg")
    assert {s["name"] for s in detail.siblings} >= {"Rouge", "Bleu", "Marron", "Vert"}
    assert detail.store_data == {}  # esta ficha no trae el código al final de la descripción
    monkeypatch.setattr(browser, "active", lambda: False)
    with pytest.raises(NeedsBrowser):
        sizeofficial.SizeConnector().detail({"handle": "19750826"})
    with pytest.raises(SearchError):
        sizeofficial.SizeConnector().search("https://www.sizeofficial.fr/products/19750826")


# ---------- Foot Locker


def test_foot_locker_lee_el_html_por_facetas_sin_paginar(monkeypatch):
    loader = _json("footlocker_listado.json")
    listing = footlocker.block(loader["loaderData"], "products")
    products = footlocker.parse_listing(listing, "chaussures")
    assert [(p.product_ref, p.brand, p.name, p.store_color, p.color, p.price_cents) for p in products] == [
        ("footlocker:314206535404", "Nike", "Air Max Tuned 1", "Black-Black-Black", "negro", 18999),
        ("footlocker:314219147304", "Nike", "Air Max Tuned 1 Bat", "Dk Smoke Grey-Chrome Yellow-Black", "gris", 18999),
    ]
    assert products[0].url == "https://www.footlocker.fr/fr/product/~/314206535404.html"
    # Marcas y «Nouveautés», ordenadas por novedad; ni rebajas ni «solo en Foot Locker».
    facets = footlocker.facet_queries(listing)
    assert facets[0] == ":newArrivals:collection_id:men-shoes:brand:adidas"
    assert ":newArrivals:collection_id:men-shoes:newArrival:True" in facets
    assert not any("saleProduct" in f or "footLockerOnly" in f for f in facets)
    assert footlocker.first_color("White Black-White Black") == "blanco"

    connector = footlocker.FootLockerConnector(pause=0)
    connector.fetcher = FakeFetcher({"/fr/search?query=": (200, _hydration(loader))})
    monkeypatch.setattr(crawl, "max_pages", lambda store: 3)  # la primera y dos facetas
    found = connector.list_category("chaussures")
    assert [p.product_ref for p in found] == ["footlocker:314206535404", "footlocker:314219147304"]
    assert connector.fetcher.asked == [
        "https://www.footlocker.fr/fr/search?query=:newArrivals:collection_id:men-shoes",
        "https://www.footlocker.fr/fr/search?query=:newArrivals:collection_id:men-shoes:brand:adidas",
        "https://www.footlocker.fr/fr/search?query=:newArrivals:collection_id:men-shoes:newArrival:True",
    ]
    assert not any("/zgw/" in url for url in connector.fetcher.asked)


def test_foot_locker_ficha_con_codigo_de_fabricante_tallas_y_fotos_sobre_blanco():
    product_block = footlocker.block(_json("footlocker_ficha.json")["loaderData"], "product")
    info, detail = footlocker.parse_product(product_block)
    assert info["brand"] == "Nike" and detail.store_data == {"mpn": "DM0032-020"}
    assert footlocker.reference({"sku": "314217089904", "mpn": "DM0032-020"}) == "DM0032-020"
    assert detail.price_cents == 15000 and detail.store_color == "Noir"
    assert detail.sizes[0] == {"name": "40", "in_stock": True}
    # Lateral, tres cuartos, tres cuartos trasera y cenital (la suela, 06, no).
    assert [u.split("?")[0].rsplit("/", 1)[-1] for u in detail.photo_urls] == [
        "314217089904_01", "314217089904_02", "314217089904_03", "314217089904_05"]
    assert all("bgc=255,255,255" in u for u in detail.photo_urls)
    assert [s["product_ref"] for s in detail.siblings] == [
        "footlocker:314206116304", "footlocker:314206535404", "footlocker:314217089904"]
    assert "assisté par l'IA" not in detail.description
    # Su CDN manda las fotos con el fondo transparente: se ponen sobre blanco (si no, sale negro).
    clear = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    buffer = io.BytesIO()
    clear.save(buffer, "PNG")
    flat = Image.open(io.BytesIO(footlocker.on_white(buffer.getvalue())))
    assert flat.mode == "RGB" and flat.getpixel((1, 1)) == (255, 255, 255)


def test_el_buscador_de_foot_locker_entiende_enlace_numero_y_codigo():
    assert footlocker.parse_query("https://www.footlocker.fr/fr/product/nike-x/314217089904.html") == (
        "sku", "314217089904")
    assert footlocker.parse_query("314217089904") == ("sku", "314217089904")
    assert footlocker.parse_query("réf DM0032-020") == ("code", "DM0032-020")
    with pytest.raises(NotThisStore):
        footlocker.parse_query("zapatillas negras")


# ---------- Jules


def test_jules_lee_la_rejilla_y_la_ficha_desde_dentro_de_la_pagina(monkeypatch):
    grid = _text("jules_grid.html")
    products = jules.parse_grid(grid, "t-shirt")
    assert [(p.product_ref, p.name, p.type, p.price_cents, p.color) for p in products] == [
        ("jules:100971710001", "Tee shirt imprimé San Antonio Spurs licence NBA", "camiseta", 1599, ""),
        ("jules:100977618422", "Tee shirt imprimé New York Knicks licence NBA", "camiseta", 1599, ""),
        ("jules:100964410002", "Tee shirt 100% coton brodé poitrine Noël", "camiseta", 1999, ""),
    ]
    assert products[0].url == "https://www.jules.com/fr-fr/p/100971710001.html"
    variation = _json("jules_variation.json")
    session = _browser(monkeypatch, FakeBrowser(
        pages={"/fr-fr/l/t-shirt/": (200, "<html>Jules</html>")},
        texts={"Search-UpdateGrid?cgid=HCC25&start=0&sz=32": (200, grid)},
        jsons={"Product-Variation?pid=7275939010": (200, variation)},
    ))
    connector = jules.JulesConnector()
    assert len(connector.list_category("t-shirt")) == 3  # menos de 32: no hay más páginas
    detail = connector.detail({"pid": "7275939010"})
    assert session.asked == [
        "https://www.jules.com/fr-fr/l/t-shirt/",
        "https://www.jules.com/on/demandware.store/Sites-Jules-SFRA-Site/fr_FR/Search-UpdateGrid?cgid=HCC25&start=0&sz=32",
        "https://www.jules.com/on/demandware.store/Sites-Jules-SFRA-Site/fr_FR/Product-Variation?pid=7275939010",
    ]
    # Una sola foto sin modelo: la de delante (_V11).
    assert [u.split("?")[0].rsplit("/", 1)[-1] for u in detail.photo_urls] == ["727593_9010_V11.jpg"]
    assert detail.store_color == "Blanc" and detail.price_cents == 1599
    assert detail.composition == "Composition principale: 100% Coton"
    assert [s["name"] for s in detail.sizes] == ["XS", "S", "M", "L", "XL", "XXL", "XXXL"]
    # El pid de otro color: el modelo (masterID) + el id del color. El propio también está.
    assert [(s["product_ref"], s["name"]) for s in detail.siblings] == [
        ("jules:72759310147", "Écru"), ("jules:72759311010", "Bleu clair"), ("jules:72759311052", "Bleu clair"),
        ("jules:7275939010", "Blanc"),
    ]
    # Una cazadora con cremallera en Sudaderas es una sudadera (como en Carhartt WIP).
    zip_up = sfra.make_product(jules.SITE, pid="1", name="Veste zippée sherpa", price=3999, url="u", section="sweat",
                               default_type="sudadera")
    assert zip_up.type == "sudadera"


def test_jules_y_bonobo_no_abren_el_navegador_dentro_de_una_peticion(monkeypatch):
    monkeypatch.setattr(browser, "active", lambda: False)
    for connector in (jules.JulesConnector(), bonobo.BonoboConnector()):
        with pytest.raises(NeedsBrowser):
            connector.detail({"pid": "7275939010"})
    with pytest.raises(SearchError):
        jules.JulesConnector().search("https://www.jules.com/fr-fr/p/7275939010.html")
    with pytest.raises(NotThisStore):
        bonobo.BonoboConnector().search("https://www.jules.com/fr-fr/p/7275939010.html")


# ---------- Bonobo


def test_bonobo_separa_el_color_del_nombre_y_trae_sus_otros_colores(monkeypatch):
    grid = _text("bonobo_grid.html")
    products = bonobo.parse_grid(grid, "sweats")
    assert [(p.product_ref, p.name, p.store_color, p.color, p.type, p.price_cents) for p in products] == [
        ("bonobo:36125281290590267", "Polo droit manches longues en coton", "Vert kaki", "verde oliva", "polo", 3999),
        ("bonobo:36125281290590930", "Polo droit manches longues en coton", "Ecru", "crudo", "polo", 3999),
        ("bonobo:36125281290504452", "Sweat droit sherpa à capuche", "Sable", "beige", "sudadera", 5599),
    ]
    first = products[0]
    assert first.url == ("https://www.bonoboplanet.com/polo-droit-manches-longues-en-coton-vert-kaki-homme-"
                         "36125281290590267.html")
    assert [c["name"] for c in first.store_data["colors"]] == ["vert kaki", "ecru", "prune", "bleu marine"]
    assert first.store_data["colors"][1]["url"].endswith("-ecru-homme-36125281290590930.html")

    variation = _json("bonobo_variation.json")
    session = _browser(monkeypatch, FakeBrowser(
        host="https://www.bonoboplanet.com/sweats-homme-sch_011200",
        jsons={"Product-Variation?pid=36125281290590267": (200, variation)},
        images={"vue3": b"foto"},
    ))
    connector = bonobo.BonoboConnector()
    detail = connector.detail(first.store_data)
    # La de delante sin modelo (vue3), por su CDN de fotos; la composición, sin la letra pequeña.
    assert [u.split("?")[0].rsplit("/", 1)[-1] for u in detail.photo_urls] == [
        "veste-droite-sherpa-manches-longues-ecru-homme-vue3-36125281290530930.jpg"]
    assert detail.photo_urls[0].startswith("https://www.bonoboplanet.com/dw/image/v2/BCHM_PRD/on/demandware.static/")
    assert detail.composition == "Tissu principal : 100% POLYESTER"
    assert detail.store_color == "Ecru" and detail.price_cents == 4199
    assert [(s["product_ref"], s["name"]) for s in detail.siblings] == [
        ("bonobo:36125281290590267", "Vert kaki"), ("bonobo:36125281290590309", "Prune"),
        ("bonobo:36125281290590930", "Ecru"), ("bonobo:36125281290593533", "Bleu marine"),
    ]
    # Sus fotos tampoco responden a un cliente normal: se abren en la propia sesión del navegador.
    assert connector.download(detail.photo_urls[0]) == b"foto"
    assert session.asked[-1] == detail.photo_urls[0]


# ---------- Nacen desactivadas, el panel y el reparto de noches


def test_las_cinco_nuevas_nacen_desactivadas_con_su_clase_de_ropa_y_su_dia(client):
    stores = {s["key"]: s for s in client.get("/api/shop/state").json()["stores"]}
    for key in NUEVAS:
        assert stores[key]["enabled"] is False and stores[key]["next_check"] is None
    for key in ("snipes", "size", "footlocker"):
        assert stores[key]["kinds"] == ["calzado"] and stores[key]["heavy"] is False
    assert "capa_exterior" in stores["jules"]["kinds"] and "calzado" in stores["bonobo"]["kinds"]
    assert stores["jules"]["heavy"] and stores["bonobo"]["heavy"]
    assert [stores[k]["browser"] for k in NUEVAS] == [True, True, False, True, True]
    assert [stores[k]["weekday"] for k in NUEVAS] == [5, 6, 4, 2, 4]


def test_con_las_veinte_tiendas_cada_noche_cabe():
    # Las quince de antes y las cinco últimas (Uniqlo, Mango, H&M, COS y Weekday) en sus huecos previstos.
    plan = shopping.week_plan()
    assert sum(map(len, plan)) == len(shops.CONNECTORS) == 20
    assert (config.SHOP_STORES_PER_NIGHT, config.SHOP_HEAVY_PER_NIGHT) == (3, 2)
    for day in plan:
        assert len(day) <= 3 and sum(map(shops.heavy, day)) <= 2
    assert [day for day in plan if {"uniqlo", "mango", "hm", "cos", "weekday"} & set(day)] == [
        ["pullandbear", "jackjones", "uniqlo"], ["courir", "massimodutti", "mango"], ["bershka", "nike", "hm"],
        ["lefties", "snipes", "cos"], ["size", "weekday"],
    ]
    assert sum(map(shops.heavy, shops.CONNECTORS)) == 11


# ---------- La misma zapatilla en varias tiendas


class CodeConnector(FakeConnector):
    """Una tienda de zapatillas de mentira que sabe el código de fabricante (en `store_data["mpn"]`)."""

    categories = {"zapatillas": "Zapatillas"}

    def maker_code(self, store_data):
        return store_data.get("mpn")


@pytest.fixture
def zapatillerias(monkeypatch, photo_bytes):
    def install(**by_store) -> dict[str, CodeConnector]:
        made = {}
        for key, products in by_store.items():
            connector = CodeConnector(photo_bytes, key, shops.CONNECTORS[key].name, zapatillas=products)
            monkeypatch.setitem(shops.CONNECTORS, key, connector)
            made[key] = connector
        with SessionLocal() as db:
            for key in by_store:
                shopping.set_store(db, key, True, ["zapatillas"])
        return made

    return install


def _shoe(store: str, ref: str, price: int, mpn: str | None) -> object:
    shoe = product(ref, "zapatillas", "blanco", price=price, section="zapatillas", store=store,
                   name="Air Force 1 '07")
    if mpn:
        shoe.store_data["mpn"] = mpn
    return shoe


def test_la_misma_zapatilla_de_dos_tiendas_sale_una_vez_la_mas_barata_y_el_visor_dice_donde_mas(
        client, zapatillerias):
    zapatillerias(
        courir=[_shoe("courir", "c1", 11999, "CW2288-111"), _shoe("courir", "c2", 9999, "DD1391-100")],
        snipes=[_shoe("snipes", "s1", 10999, "CW2288 111")],
    )
    _refresh(stores=["courir"])
    _refresh(stores=["snipes"])
    new = {item.product_ref for item in _items("nuevo")}
    # La de Courir salió primero, pero la de Snipes es la misma y más barata: se queda la de Snipes.
    assert new == {"snipes:s1", "courir:c2"}
    with SessionLocal() as db:
        courir = db.scalars(select(ShopItem).where(ShopItem.product_ref == "courir:c1")).one()
        assert courir.status == "candidato" and courir.photos == [] and courir.maker_code == "CW2288111"
    shown = client.get("/api/shop/next", params={"store": "snipes"}).json()["item"]
    assert shown["product_ref"] == "snipes:s1"
    assert shown["also_in"] == [{"store": "courir", "store_name": "Courir", "price_cents": 11999,
                                 "url": "https://tienda.test/c1"}]
    # Sin código no se compara nada: la de otra tienda sin código no dice «También en».
    other = client.get("/api/shop/next", params={"store": "courir"}).json()["item"]
    assert other["product_ref"] == "courir:c2"
    assert other["also_in"] == []


def test_si_ya_se_dijo_algo_de_esa_zapatilla_no_vuelve_desde_otra_tienda(client, zapatillerias):
    zapatillerias(courir=[_shoe("courir", "c1", 11999, "CW2288-111")])
    _refresh(stores=["courir"])
    with SessionLocal() as db:
        item = db.scalars(select(ShopItem).where(ShopItem.product_ref == "courir:c1")).one()
        shopping.dislike(db, item)
    zapatillerias(snipes=[_shoe("snipes", "s1", 8999, "CW2288-111"), _shoe("snipes", "s2", 8999, None)])
    _refresh(stores=["snipes"])
    assert {item.product_ref for item in _items("nuevo")} == {"snipes:s2"}


def test_el_codigo_que_solo_dice_la_ficha_tambien_cuenta(client, zapatillerias):
    # Snipes, size? y Foot Locker solo dicen el código en la ficha: se mira al leerla.
    stores = zapatillerias(courir=[_shoe("courir", "c1", 9999, "CW2288-111")],
                           footlocker=[_shoe("footlocker", "f1", 12000, None)])
    stores["footlocker"].details["f1"] = ShopDetail(
        price_cents=None, sizes=[{"name": "42", "in_stock": True}], photo_urls=["https://fotos.test/f1.jpg"],
        store_data={"mpn": "CW2288-111"},
    )
    _refresh(stores=["courir"])
    _refresh(stores=["footlocker"])
    assert {item.product_ref for item in _items("nuevo")} == {"courir:c1"}
    assert stores["footlocker"].asked("foto") == []  # se vio en la ficha: ni se bajaron sus fotos
    with SessionLocal() as db:
        row = db.scalars(select(ShopItem).where(ShopItem.product_ref == "footlocker:f1")).one()
        assert row.status == "candidato" and row.maker_code == "CW2288111"
        courir = db.scalars(select(ShopItem).where(ShopItem.product_ref == "courir:c1")).one()
        assert shopping.also_in(courir) == [{"store": "footlocker", "store_name": "Foot Locker",
                                             "price_cents": 12000, "url": "https://tienda.test/f1"}]


def test_la_clave_del_codigo_de_fabricante():
    assert shops.maker_key("CW2288-111") == shops.maker_key("cw2288 111") == "CW2288111"
    assert shops.maker_key("1203A739-200") == "1203A739200"
    assert shops.maker_key("555088-134") == "555088134"  # las Jordan de siempre: solo cifras, pero con guion
    assert shops.maker_key("01126425") is None  # un número interno de la tienda, no un código de modelo
    assert shops.maker_key("") is None and shops.maker_key("AB1") is None
