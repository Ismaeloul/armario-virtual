"""Las cinco tiendas del 18-11-2026 (Massimo Dutti, Lefties, Nike, Jack & Jones y Carhartt WIP), el reparto
de noches, el color desconocido y el aviso de Descubrir. Todo sin red ni navegador: los fragmentos reales
recortados en la investigación y sesiones o clientes falsos."""
import json
from datetime import datetime, timedelta

import pytest
from test_shop import FIXTURES, product
from test_shop_navegador import FakeSession, _con_sesion, sin_navegador  # noqa: F401  (fixture)

from app import config
from app.db import SessionLocal
from app.services import shopping, shops
from app.services.shops import BlockedError, NotThisStore, SearchError, browser, carhartt, courir, estimate
from app.services.shops import fetch, inditex, jackjones, lefties, massimodutti, nike

_REAL_FETCHER_GET = fetch.Fetcher.__dict__["get"]


def _json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _photo_names(urls):
    return [u.split("?")[0].rsplit("/", 1)[-1] for u in urls]


class FakeFetcher:
    """Lo que el conector le pide a la tienda: dirección -> (estado, texto). Apunta lo pedido."""

    def __init__(self, pages: dict):
        self.pages = pages
        self.asked: list[str] = []

    def get(self, url, accept=None, pause=None):
        self.asked.append(url)
        for part, (status, body) in self.pages.items():
            if part in url:
                return fetch.Page(status, body.encode("utf-8") if isinstance(body, str) else body)
        return fetch.Page(404, b"")


# ---------- Massimo Dutti y Lefties: la base de Inditex


def test_massimo_dutti_lee_sus_fichas_con_fotos_sin_modelo_delante_y_detras():
    products = inditex.parse_products(_json("massimodutti_camisas.json")["products"], massimodutti.SITE,
                                      "chemises-n1356")
    assert [(p.product_ref, p.name, p.store_color, p.color, p.type, p.price_cents) for p in products] == [
        ("massimodutti:68697911-710", "Chemise regular fit 100 % coton", "BEIGE", "beige", "camisa", 7000),
        ("massimodutti:68690842-706", "Chemise regular fit 100 % coton chiné", "VISON", "beige", "camisa", 7000),
    ]
    first = products[0]
    assert first.url == ("https://www.massimodutti.com/fr/chemise-regular-fit-100--coton-l02121393"
                         "?colorId=710&pelement=68699057")
    assert inditex.reference(first.store_data) == "2121/393/710"
    detail = inditex.detail_from(massimodutti.SITE, first.store_data)
    # o1 delante y o3 detrás, sin modelo.
    assert _photo_names(detail.photo_urls) == ["02121393710-o1.jpg", "02121393710-o3.jpg"]
    assert detail.composition == "Extérieur: 100% coton" and detail.sizes[0] == {"name": "S", "in_stock": True}
    # El de dos colores trae a su hermano.
    siblings = inditex.detail_from(massimodutti.SITE, products[1].store_data).siblings
    assert [s["product_ref"] for s in siblings] == ["massimodutti:68690842-706", "massimodutti:68690842-250"]
    # Calzado: lateral, el par en tres cuartos y desde arriba.
    shoe = inditex.parse_products(_json("massimodutti_calzado.json")["products"], massimodutti.SITE,
                                  "chaussures-n1420")[0]
    assert (shoe.name, shoe.type, shoe.color, shoe.price_cents) == ("Baskets en cuir souple", "zapatillas", "marrón", 14000)
    assert _photo_names(inditex.detail_from(massimodutti.SITE, shoe.store_data).photo_urls) == [
        "12132850707-o1.jpg", "12132850707-o2.jpg", "12132850707-o3.jpg",
    ]


def test_lefties_enlaza_con_el_producto_de_dentro_y_solo_tiene_foto_de_delante():
    products = inditex.parse_products(_json("lefties_camisetas.json")["products"], lefties.SITE,
                                      "t-shirts-c1030267569")
    assert [(p.product_ref, p.name, p.store_color, p.color, p.price_cents) for p in products] == [
        ("lefties:762111557-818", "T-shirt double manche", "PLOMB", "gris", 1299),
        ("lefties:762111978-820", "T-shirt slim texturé", "ACIER", "gris", 1299),
    ]
    # El id del enlace es el del producto de dentro (el que abre la ficha buena), no el del «bundle».
    assert products[0].url == "https://www.lefties.com/fr/t-shirt-double-manche-c0p762111557.html?colorId=818"
    assert products[1].pattern == "texturizado" and inditex.reference(products[0].store_data) == "5027/525/818"
    detail = inditex.detail_from(lefties.SITE, products[0].store_data)
    assert _photo_names(detail.photo_urls) == ["05027525818-P.jpg"] and detail.store_data == {}
    assert len(detail.siblings) == 2
    # Un nombre en MAYÚSCULAS pasa a formato de frase; calzado con sus tres vistas.
    shoe = inditex.parse_products(_json("lefties_calzado.json")["products"], lefties.SITE, "baskets-c1030272289")[0]
    assert (shoe.name, shoe.type, shoe.color) == ("Basket combinée", "zapatillas", "gris")
    assert _photo_names(inditex.detail_from(lefties.SITE, shoe.store_data).photo_urls) == [
        "12020790004-A1.jpg", "12020790004-A2.jpg", "12020790004-A3.jpg",
    ]


MD_ARRAY = ("https://www.massimodutti.com/itxrest/3/catalog/store/34009451/30359524/productsArray"
            "?languageId=-2&productIds=67860641&appId=1")


def test_massimo_dutti_pide_su_categoria_desde_la_pagina_porque_ella_no_la_pide(monkeypatch):
    camisas = _json("massimodutti_camisas.json")["products"]
    session = FakeSession(
        # La página solo pide la primera tanda de fichas (y alguna ficha de otra cosa, que no cuenta).
        responses=[browser.Response(MD_ARRAY, 200, {"products": camisas[:1] + [{"id": 1, "name": "Otra cosa"}]})],
        fetched={
            "/category/680504/product": (200, {"sortedProductIds": [c["id"] for c in camisas]}),
            "productsArray": (200, {"products": camisas[1:]}),
        },
    )
    _con_sesion(monkeypatch, session)
    found = massimodutti.MassimoDuttiConnector().list_category("chemises-n1356")
    assert session.opened == ["https://www.massimodutti.com/fr/homme/chemises-n1356"]
    assert session.asked[0] == ("https://www.massimodutti.com/itxrest/3/catalog/store/34009451/30359524/category/680504"
                                "/product?languageId=-2&appId=1&showProducts=false")
    assert f"productIds={camisas[1]['id']}" in session.asked[1] and len(session.asked) == 2
    assert [p.product_ref for p in found] == ["massimodutti:68697911-710", "massimodutti:68690842-706"]


def test_lefties_oye_su_categoria_como_bershka(monkeypatch):
    camisetas = _json("lefties_camisetas.json")["products"]
    base = "https://www.lefties.com/itxrest/3/catalog/store/94009001/90009053"
    session = FakeSession(responses=[
        browser.Response(f"{base}/category/1030267569/product?showProducts=false&languageId=-2&appId=1", 200,
                         _json("lefties_categoria.json")),
        browser.Response(f"{base}/productsArray?productIds=762114572,762114575&languageId=-2&appId=1", 200,
                         {"products": camisetas}),
    ])
    _con_sesion(monkeypatch, session)
    found = lefties.LeftiesConnector().list_category("t-shirts-c1030267569")
    assert session.opened == ["https://www.lefties.com/fr/homme/v%C3%AAtements/t-shirts-c1030267569.html"]
    assert session.asked == [] and len(found) == 2  # todo venía en la página


# ---------- Nike: solo zapatillas, sin navegador


def test_nike_lee_el_listado_con_marca_color_por_tono_y_codigo():
    products = nike.parse_wall(nike.wall(_json("nike_listado.json"))["productGroupings"], "chaussures")
    assert [(p.product_ref, p.name, p.brand, p.color, p.price_cents) for p in products] == [
        ("nike:HM6803-019", "Vomero 18", "Nike", "negro", 9599),
        ("nike:HM6803-101", "Vomero 18", "Nike", "blanco", 9599),
        ("nike:HQ2592-017", "Pegasus Premium", "Nike", "gris", 12599),
        ("nike:HQ2592-110", "Pegasus Premium", "Nike", "blanco", 12599),
    ]
    first = products[0]
    assert (first.type, first.category, first.style) == ("zapatillas", "calzado", "deportivo")
    assert first.store_color == "Noir/University Red/Anthracite/Bright Crimson"
    assert first.url.endswith("/HM6803-019") and nike.reference(first.store_data) == "HM6803-019"
    # Las chanclas y sandalias no entran.
    sandal = {"productCode": "AB1234-001", "productType": "FOOTWEAR", "copy": {"title": "Nike Calm",
              "subTitle": "Claquette pour homme"}, "prices": {"currentPrice": 40}}
    assert nike.make_product(sandal, "chaussures") is None
    # El color, por el tono si la palabra dice poco.
    tono = {**sandal, "copy": {"title": "Nike Air", "subTitle": "Chaussure pour homme"},
            "displayColors": {"simpleColor": {"label": "Phantom", "hex": "101010"}}}
    assert nike.make_product(tono, "chaussures").color == "negro"


def test_la_ficha_de_nike_sale_sin_tallas_y_disponible_mientras_se_venda():
    item, detail = nike.parse_product_page(_json("nike_ficha.json"))
    assert detail.price_cents == 9599 and detail.sizes == [] and detail.in_stock
    assert not detail.stock_known
    # Lateral, el par en tres cuartos, desde arriba y trasera (nunca la suela, la segunda).
    photos = _json("nike_ficha.json")["props"]["pageProps"]["selectedProduct"]["contentImages"]
    squares = [c["properties"]["squarish"]["url"] for c in photos]
    assert detail.photo_urls == [squares[0], squares[4], squares[3], squares[5]]
    assert "nike:HM6803-019" in [s["product_ref"] for s in detail.siblings] and len(detail.siblings) >= 2
    assert detail.description.startswith("Amorti énorme")
    assert nike.make_product(item, "").product_ref == "nike:HM6803-019"
    # Agotada: la tienda ya no la vende.
    data = _json("nike_ficha.json")
    data["props"]["pageProps"]["selectedProduct"]["statusModifier"] = "OUT_OF_STOCK"
    assert not nike.parse_product_page(data)[1].in_stock


def test_nike_sigue_la_paginacion_que_pide_la_propia_web_sin_cabeceras_copiadas(monkeypatch):
    listado = _json("nike_listado.json")
    following = listado["props"]["pageProps"]["initialState"]["Wall"]["pageData"]["next"]
    api = _json("nike_listado_api.json")
    api["pages"]["next"] = ""  # la última
    page = f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(listado)}</script></html>'
    fake = FakeFetcher({"/fr/w/hommes-chaussures-nik1zy7ok?sortBy=newest": (200, page),
                        "api.nike.com/discover/product_wall": (200, json.dumps(api))})
    connector = nike.NikeConnector()
    connector.fetcher = fake
    found = connector.list_category("chaussures")
    assert fake.asked == ["https://www.nike.com/fr/w/hommes-chaussures-nik1zy7ok?sortBy=newest",
                          "https://api.nike.com" + following]
    assert len(found) == 6 and found[-1].product_ref == "nike:IX7726-068"
    # Si la segunda falla, lo leído se guarda (`Partial`).
    fake.pages["api.nike.com/discover/product_wall"] = (500, "")
    with pytest.raises(shops.Partial) as partial:
        connector.list_category("chaussures")
    assert len(partial.value.products) == 4


def test_el_buscador_de_nike_entiende_codigos_y_enlaces():
    assert nike.parse_query("HM6803-019") == "HM6803-019"
    assert nike.parse_query("réf. hm6803-019") == "HM6803-019"
    assert nike.parse_query("Référence HM6803-019") == "HM6803-019"
    assert nike.parse_query("https://www.nike.com/fr/t/chaussure-vomero-18-SMtmxlKz/HM6803-019") == "HM6803-019"
    assert nike.parse_query("555088-134") == "555088-134"
    for otra in ("3918/300", "1203A739-200", "zapatillas blancas", "https://www.courir.com/fr/p/x-1514875.html"):
        with pytest.raises(NotThisStore):
            nike.parse_query(otra)
    with pytest.raises(SearchError):
        nike.parse_query("https://www.nike.com/fr/w/hommes-chaussures-nik1zy7ok")


# ---------- Jack & Jones


def test_jack_and_jones_completa_el_nombre_con_su_enlace_y_lee_el_color_de_la_familia():
    products = jackjones.parse_listing(jackjones.listing(_json("jackjones_listado.json")), "t-shirts")
    assert [(p.product_ref, p.name, p.store_color, p.color, p.type, p.price_cents, p.brand) for p in products] == [
        ("jackjones:12308540_2036", "T-shirt standard fit col rond", "Grise", "gris", "camiseta", 1299, ""),
        ("jackjones:12308540_1966", "T-shirt standard fit col rond", "Bleue", "azul", "camiseta", 1299, ""),
        ("jackjones:12308757_6", "T-shirt à manches longues relaxed fit col rond", "Blanche", "blanco", "camiseta",
         2999, ""),
    ]
    assert products[0].url == "https://www.jackjones.com/fr-fr/product/12308540_2036/t-shirts-standard-fit-col-rond"
    assert jackjones.reference(products[0].store_data) == "12308540"
    assert jackjones.full_name("Parka", "/fr-fr/product/1_2/parkas-a-capuche") == "Parka a capuche"


def test_la_ficha_de_jack_and_jones_da_tallas_fotos_sin_modelo_tono_y_colores():
    detail = jackjones.parse_product(_json("jackjones_ficha.json")["product"])
    assert detail.price_cents == 1299 and detail.in_stock and detail.sizes[0] == {"name": "XS", "in_stock": True}
    assert [s["name"] for s in detail.sizes][:3] == ["XS", "S", "M"]  # en su orden (la web las da desordenadas)
    # 001 delante y 002 detrás (sin modelo; las de modelo son de IA), en JPG de 1280 px con fondo blanco.
    assert [u.split("/")[5] for u in detail.photo_urls] == ["001", "002"]
    assert all("format=jpg&width=1280" in u for u in detail.photo_urls)
    assert detail.color_hex == "#58646d" and detail.store_color == "Gris foncé"
    assert detail.composition == "100% Coton" and detail.store_data == {"style": "12308540"}
    assert [(s["product_ref"], s["hex"]) for s in detail.siblings] == [
        ("jackjones:12308540_1466", "#8a9691"), ("jackjones:12308540_1966", "#9eb4d3"),
        ("jackjones:12308540_2036", "#58646d"),
    ]
    # Si solo hubiera fotos de modelo: la primera, y se dice.
    only_model = {**_json("jackjones_ficha.json")["product"]}
    only_model["media"] = [m for m in only_model["media"] if m["aiGenerated"]]
    model = jackjones.parse_product(only_model)
    assert len(model.photo_urls) == 1 and model.store_data["model_photo"] is True


def test_jack_and_jones_recorre_la_seccion_pagina_a_pagina(monkeypatch):
    state = _json("jackjones_listado.json")
    key = next(k for k in state if k.startswith("$getProducts"))
    state[key]["totalResults"] = 61  # dos páginas de 60

    def page(data):
        return f"<script>window.__INITIAL_STATE__ = {json.dumps(data)};</script>"

    second = json.loads(json.dumps(state))
    second[key]["results"] = second[key]["results"][2:]
    fake = FakeFetcher({"t-shirts?page=2": (200, page(second)), "/fr-fr/t-shirts": (200, page(state))})
    connector = jackjones.JackJonesConnector()
    connector.fetcher = fake
    found = connector.list_category("t-shirts")
    assert fake.asked == ["https://www.jackjones.com/fr-fr/t-shirts", "https://www.jackjones.com/fr-fr/t-shirts?page=2"]
    assert len(found) == 3  # la segunda repetía uno


def test_el_buscador_de_jack_and_jones_no_se_mete_en_lo_de_las_demas():
    assert jackjones.parse_query("https://www.jackjones.com/fr-fr/product/12308540_2036/t-shirts")[0] == "link"
    assert jackjones.parse_query("12308540_2036") == ("ref", "12308540_2036")
    # Ni el número de estilo a secas (choca con las referencias de Zara de ocho cifras) ni texto libre.
    for otra in ("03918300", "12308540", "camiseta blanca", "https://www.zara.com/fr/fr/x-p03918300.html"):
        with pytest.raises(NotThisStore):
            jackjones.parse_query(otra)


# ---------- Carhartt WIP


def test_carhartt_lee_el_flujo_de_next_y_las_sobrecamisas_van_aparte():
    products, total = carhartt.parse_listing(_text("carhartt_listado.html"), "homme-vestes-et-manteaux")
    assert total == 153
    assert [(p.product_ref, p.name, p.store_color, p.color, p.pattern, p.type, p.price_cents) for p in products] == [
        ("carhartt:I037808_41S_XX", "L/S Asner Shirt Jac", "Asner Check, Duck Blue", "azul", "cuadros", "sobrecamisa",
         12900),
        ("carhartt:I037807_00E_XX", "Mitch Shirt Jac", "Black / Black", "negro", "liso", "sobrecamisa", 14900),
        ("carhartt:I037808_41U_XX", "L/S Asner Shirt Jac", "Asner Check, Graphite", "gris", "cuadros", "sobrecamisa",
         12900),
    ]
    assert products[0].url == "https://www.carhartt-wip.com/fr-fr/p/l-s-asner-shirt-jac-asner-check-duck-blue-1074"
    assert carhartt.reference(products[0].store_data) == "I037808"
    # La manga larga en inglés («L/S») no es ropa de verano.
    assert not shopping.summer_text("L/S Asner Shirt Jac") and shopping.summer_text("S/S Pocket T-Shirt")


def test_la_ficha_de_carhartt_da_tallas_fotos_sin_modelo_composicion_y_colores():
    detail = carhartt.parse_product(_text("carhartt_ficha.html"), "I037783_89_XX")
    assert detail.price_cents == 13900 and [s["name"] for s in detail.sizes] == ["XS", "S", "M", "L", "XL", "XXL"]
    assert all(s["in_stock"] for s in detail.sizes)
    assert detail.photo_urls == [
        "https://cdn.media.amplience.net/i/carhartt_wip/I037783_89_XX-ST-01?$ST$&w=1280&fmt=jpg",
        "https://cdn.media.amplience.net/i/carhartt_wip/I037783_89_XX-ST-02?$ST$&w=1280&fmt=jpg",
    ]
    assert detail.composition == "Dessus: 20% Polyester, 80% Coton · Côtes: 3% Polyester, 97% Coton"
    assert detail.store_color == "Black"
    assert [(s["product_ref"], s["name"]) for s in detail.siblings] == [
        ("carhartt:I037783_482_XX", "Ash Heather"), ("carhartt:I037783_89_XX", "Black"),
    ]
    assert carhartt.parse_product("<html>nada</html>", "x") is None  # ya no existe


def test_el_buscador_de_carhartt_solo_entiende_enlaces():
    assert carhartt.parse_query("https://www.carhartt-wip.com/fr-fr/p/hooded-tyson-jacket-black-1142") == (
        "hooded-tyson-jacket-black-1142")
    for otra in ("I037783", "chaqueta negra", "https://www.zara.com/fr/fr/x.html"):
        with pytest.raises(NotThisStore):
            carhartt.parse_query(otra)


# ---------- Vocabulario en inglés


@pytest.mark.parametrize(
    ("name", "default", "expected"),
    [
        ("Hooded Tyson Jacket", None, "chaqueta"), ("Mitch Shirt Jac", None, "sobrecamisa"),
        ("Nelson Sweat Pant", None, "chándal"), ("Single Knee Pant", None, "pantalón"),
        ("S/S Pocket T-Shirt", None, "camiseta"), ("Chase Sweatshirt", None, "sudadera"),
        ("Madison Shirt", None, "camisa"), ("Chore Coat", None, "abrigo"), ("Chase Hoodie", None, "sudadera"),
        ("Script Cap", "camiseta", None), ("Jake Belt", "pantalón", None),
    ],
)
def test_el_tipo_se_entiende_en_ingles(name, default, expected):
    assert estimate.estimate_type(name, default) == expected


# ---------- Que nacen desactivadas y el reparto de noches


def test_las_cinco_nuevas_nacen_desactivadas_y_con_su_clase_de_ropa(client):
    stores = {s["key"]: s for s in client.get("/api/shop/state").json()["stores"]}
    for key in ("massimodutti", "lefties", "nike", "jackjones", "carhartt"):
        assert stores[key]["enabled"] is False and stores[key]["next_check"] is None
    assert stores["nike"]["kinds"] == ["calzado"] and stores["courir"]["kinds"] == ["calzado"]
    assert "capa_exterior" in stores["carhartt"]["kinds"] and stores["lefties"]["heavy"]
    # Con solo Camisas elegida, Zara trae partes de arriba: el aviso de Descubrir no promete otra cosa.
    state = client.patch("/api/shop/settings", json={"store": "zara", "categories": ["homme-chemises-l737"]}).json()
    assert next(s for s in state["stores"] if s["key"] == "zara")["kinds"] == ["parte_superior"]


def test_el_reparto_de_la_semana_no_pasa_de_los_topes_de_cada_noche():
    # Con quince tiendas: tres por noche y dos pesadas como mucho (ver test_shop_cinco_mas para el detalle).
    for day in shopping.week_plan():
        assert len(day) <= config.SHOP_STORES_PER_NIGHT and sum(map(shops.heavy, day)) <= config.SHOP_HEAVY_PER_NIGHT
    assert sum(map(len, shopping.week_plan())) == len(shops.CONNECTORS)


def test_si_coinciden_mas_la_noche_hace_las_que_caben_y_las_demas_esperan(client):
    with SessionLocal() as db:
        for key in shops.CONNECTORS:  # todas activadas a la vez: todas tocarían la primera noche
            shopping.set_store(db, key, True, None)
        night = datetime.combine(shopping.local_now().date() + timedelta(days=1), datetime.min.time()).replace(
            hour=3, minute=40)
        ran: list[list[str]] = []
        for _ in range(8):
            picked = shopping.tonight(db, night)
            assert len(picked) <= config.SHOP_STORES_PER_NIGHT
            assert sum(map(shops.heavy, picked)) <= config.SHOP_HEAVY_PER_NIGHT
            shopping.note_tonight(db, picked, night)
            assert shopping.tonight(db, night + timedelta(hours=2)) == []  # esa noche ya no sale ninguna más
            for store in picked:  # como si se hubieran consultado bien
                shopping._save_status(db, store, {"at": "x", "day": night.date().isoformat(), "ok": True,
                                                  "ok_day": night.date().isoformat()})
            db.commit()
            ran.append(picked)
            night += timedelta(days=1)
    # Primero las que más esperan; a igualdad, el orden del panel (y sin pasar de dos pesadas).
    assert ran[0] == ["zara", "courir", "jdsports"]
    # En ocho noches han salido todas: veinte tiendas a tres por noche, y alguna repite en su día de siempre.
    assert {s for night_ in ran for s in night_} == set(shops.CONNECTORS)


# ---------- El color desconocido no cuenta como multicolor


def test_un_color_desconocido_no_resta_como_multicolor():
    zapatilla = courir.make_product(sku="1514875", name="AIR FORCE 1 '07", brand="NIKE", url="https://x/1514875.html",
                                    price_cents=11999, section="sneakers", model="CW2288-111")
    assert zapatilla.color == estimate.UNKNOWN_COLOR == ""
    wardrobe = [shopping.candidate_item(product(f"w{i}", "camiseta", "negro")) for i in range(5)]
    wardrobe += [shopping.candidate_item(product(f"p{i}", "vaquero", "azul")) for i in range(3)]
    unknown, reasons = shopping.score(zapatilla, wardrobe)
    zapatilla.color = "multicolor"
    multi, multi_reasons = shopping.score(zapatilla, wardrobe)
    assert unknown > multi
    assert any("multicolor" in r["text"] for r in multi_reasons)
    assert not any("multicolor" in r["text"] or "llevas nada" in r["text"] for r in reasons)
    # Lo que se aprende de él no dice nada del color.
    taste = shopping.ShopTaste()
    zapatilla.color = ""
    taste.learn(zapatilla, True)
    assert taste.colors == {}


def test_con_la_ficha_el_color_desconocido_pasa_a_saberse():
    from app.models import ShopItem

    row = ShopItem(store="courir", product_ref="courir:1", name="Air Force 1", store_color="", color="",
                   store_data={})
    shopping._detail_color(row, shops.ShopDetail(price_cents=None, sizes=[], photo_urls=[], store_color="Blanc"))
    assert row.color == "blanco" and row.store_color == "Blanc"


# ---------- Un bloqueo sin navegador también para hasta mañana


def test_un_429_en_una_tienda_sin_navegador_la_para_hasta_manana(monkeypatch):
    monkeypatch.setattr(fetch.Fetcher, "get", _REAL_FETCHER_GET)
    calls = []

    def fake_httpx(self, url, headers):
        calls.append(url)
        return fetch.Page(429, b"")

    monkeypatch.setattr(fetch.Fetcher, "_httpx", fake_httpx)
    with pytest.raises(BlockedError, match="429"):
        nike.NikeConnector(pause=0).fetcher.get("https://www.nike.com/fr/w/x")
    assert "hasta mañana" in browser.blocked("nike")
    # Otro cliente de la misma tienda (otra consulta, el mismo día) ya ni sale.
    with pytest.raises(BlockedError):
        nike.NikeConnector(pause=0).fetcher.get("https://www.nike.com/fr/w/y")
    assert len(calls) == 1
    assert browser.blocked("jackjones") is None  # las demás tiendas, como siempre
    with SessionLocal() as db:
        assert not shopping.reachable(db, "nike")  # ni «Ver más» ni «Consultar ahora» hasta mañana
