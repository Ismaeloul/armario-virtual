"""Compras con las tiendas de Francia: Zara Francia, Courir y JD Sports, la marca y la traducción.
Todo sin red ni IA: fragmentos recortados de las páginas reales y un traductor falso."""
import json
import re

import pytest
from conftest import VALID_DRAFT, FakeAnalyzer
from test_shop import FIXTURES, INVIERNO, _fixture, _item, _items, _more, _refresh, _taste, _texts, product

from app.db import SessionLocal
from app.models import ShopItem
from app.services import outfits, shopping, storage
from app.services.ai import translate as traductor
from app.services.ai.base import AnalysisError
from app.services.shops import NotThisStore, SearchError, ShopDetail, ShopError, ShopProduct, courir, estimate, fetch
from app.services.shops import jdsports, zara

_REAL_FETCHER_GET = fetch.Fetcher.__dict__["get"]  # antes de que `sin_red` lo sustituya



@pytest.fixture
def tienda(monkeypatch, photo_bytes):
    from test_shop import FakeConnector

    from app.services import shops

    def install(key: str = "zara", name: str = "Zara", **by_section) -> FakeConnector:
        connector = FakeConnector(photo_bytes, key, name, **by_section)
        monkeypatch.setitem(shops.CONNECTORS, key, connector)
        with SessionLocal() as db:
            shopping.set_store(db, key, True, None)
        return connector

    return install


def _texto(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ---------- Zara Francia y la estimación en francés


def test_zara_francia_lee_las_categorias_con_nombres_en_frances():
    products = zara.parse_category(_fixture("zara_categoria_fr.json"), "homme-polos-l733")
    assert [(p.name, p.store_color, p.type, p.color, p.pattern) for p in products] == [
        ("Polo à structure verticale", "Blanc cassé", "polo", "crudo", "texturizado"),
        ("Polo en maille regular fit structuré", "Bleu roi", "polo", "azul", "texturizado"),
        ("Chemise en jean coupe boxy à rayures", "Bleu", "camisa", "azul", "rayas"),
        ("Polo technique à zip", "Noir", "polo", "negro", "liso"),
    ]
    assert products[3].style == "deportivo"
    assert products[0].url.startswith("https://www.zara.com/fr/fr/polo-a-structure-verticale-p")
    assert zara.SEARCH.endswith("/store/10703/query") and zara.ZaraConnector.language == "fr"
    # Las doce secciones de siempre, con su nombre en español para el panel.
    assert len(zara.ZaraConnector.categories) == 12 and zara.ZaraConnector.categories["homme-maille-l681"] == "Punto"


@pytest.mark.parametrize(
    ("name", "default", "expected"),
    [
        ("T-SHIRT BASIQUE", "camiseta", "camiseta"), ("SWEAT À CAPUCHE", "sudadera", "sudadera"),
        ("SWEAT-SHIRT COL ROND", "sudadera", "sudadera"), ("PULL COL ROULÉ", "jersey", "jersey"),
        ("CARDIGAN EN MAILLE", "jersey", "jersey"), ("CHEMISE OXFORD", "camisa", "camisa"),
        ("SURCHEMISE EN JEAN", "sobrecamisa", "sobrecamisa"), ("VESTE EN JEAN", "chaqueta", "chaqueta"),
        ("BLOUSON BOMBER", "chaqueta", "chaqueta"), ("DOUDOUNE MATELASSÉE", "chaqueta", "abrigo"),
        ("MANTEAU EN LAINE", "chaqueta", "abrigo"), ("JEAN SLIM", "vaquero", "vaquero"),
        ("PANTALON CHINO", "pantalón", "chino"), ("PANTALON JOGGING", "pantalón", "chándal"),
        ("PANTALON COURT", "pantalón", "pantalón corto"), ("BERMUDA EN LIN", "pantalón", "pantalón corto"),
        ("BASKETS RÉTRO", "zapatillas", "zapatillas"), ("BOTTINES CHELSEA", "zapatillas", "botas"),
        ("MOCASSINS EN CUIR", "zapatillas", "zapatos"), ("CHAUSSETTES PACK", "camiseta", None),
    ],
)
def test_el_tipo_se_entiende_tambien_en_frances(name, default, expected):
    assert estimate.estimate_type(name, default) == expected


@pytest.mark.parametrize(
    ("store_color", "expected"),
    [
        ("Noir", "negro"), ("Blanc", "blanco"), ("Blanc cassé", "crudo"), ("Écru", "crudo"), ("Crème", "crudo"),
        ("Gris chiné", "gris"), ("Argenté", "gris"), ("Marron", "marrón"), ("marron/blanc", "marrón"),
        ("Blanc/Noir", "blanco"), ("Bleu marine", "azul marino"), ("Marine", "azul marino"), ("Bleu", "azul"),
        ("Bleu clair", "celeste"), ("Vert", "verde"), ("Kaki", "verde oliva"), ("Rouge", "rojo"),
        ("Bordeaux", "burdeos"), ("Jaune", "amarillo"), ("Orange", "naranja"), ("Rose", "rosa"),
        ("Violet", "morado"), ("Multicolore", "multicolor"), ("Beige", "beige"),
        ("Black/Red", "negro"), ("White", "blanco"), ("Navy", "azul marino"), ("Sail/White", "crudo"),
        ("Grey", "gris"), ("Olive", "verde oliva"), ("Brown", "marrón"), ("Pink", "rosa"),
    ],
)
def test_los_colores_en_frances_e_ingles_van_a_la_paleta(store_color, expected):
    assert estimate.estimate_color(store_color) == expected


def test_estampado_estilo_y_temporada_tambien_en_frances():
    assert estimate.estimate_pattern("CHEMISE À RAYURES") == "rayas"
    assert estimate.estimate_pattern("SURCHEMISE À CARREAUX") == "cuadros"
    assert estimate.estimate_pattern("T-SHIRT IMPRIMÉ") == "gráfico"
    assert estimate.estimate_pattern("PULL EN MAILLE TEXTURÉE") == "texturizado"
    assert estimate.estimate_season("CHEMISE EN LIN", "camisa") == "verano"
    assert estimate.estimate_season("VESTE MATELASSÉE", "chaqueta") == "invierno"
    assert estimate.estimate_style("PANTALON HABILLÉ", "pantalón") == "smart casual"
    # La regla de verano lee la manga en francés (y el texto en español sigue igual).
    camisa = outfits.Item(id=1, type="camisa", category="parte_superior", color="azul", style="casual",
                          season="todo_el_ano", pattern="liso", details="Chemise à manches courtes")
    assert outfits.summer_only(camisa) is True
    polo = outfits.Item(id=2, type="polo", category="parte_superior", color="azul", style="casual",
                        season="todo_el_ano", pattern="liso", details="Polo manches longues")
    assert outfits.summer_only(polo) is False
    assert outfits.summer_only(_item(type="camisa")) is False
    assert shopping.summer_text("T-shirt manches courtes") and not shopping.summer_text("Pull manches longues")
    assert shopping.name_words("Polo en maille à manches courtes avec zip") == {"zip"}
    # Los cortes raros también se ven en francés.
    assert shopping._RISKY.search(estimate.norm("Chemise à fleurs brodée"))


# ---------- Courir


def test_courir_lee_el_listado_con_marca_precio_y_codigo_de_fabricante():
    products = courir.parse_grid(_texto("courir_listado.html"), "sneakers")
    assert [(p.name, p.brand, p.price_cents, p.store_data["model"]) for p in products] == [
        ("Air Jordan 3 Retro True Blue", "Jordan", 15000, "IF4396-104"),  # rebajada: vale el precio de oferta
        ("Gel-NYC", "ASICS", 16000, "1203A739-200"),
    ]
    first = products[0]
    assert (first.store, first.product_ref, first.type, first.category) == ("courir", "courir:1609542", "zapatillas", "calzado")
    assert first.url == "https://www.courir.com/fr/p/jordan-air-jordan-3-retro-true-blue-1609542.html"
    assert first.color == "azul"  # el listado no trae color: se adivina por el nombre («True Blue»)
    assert courir.reference(first.store_data) == "IF4396-104"
    assert courir.reference({"sku": "1609542"}) == "1609542"  # sin código de fabricante, el de Courir


def test_de_las_novedades_de_courir_solo_entra_el_calzado_de_hombre():
    products = courir.parse_grid(_texto("courir_novedades.html"), "nouveautes", only_shoes=True)
    assert products and all(p.category == "calzado" for p in products)
    assert len(courir.parse_grid(_texto("courir_novedades.html"), "nouveautes")) > len(products)


def test_la_ficha_de_courir_da_fotos_de_producto_tallas_color_y_otros_colores():
    info, detail = courir.parse_product_page(_texto("courir_producto.html"))
    assert (info["sku"], info["brand"], info["model"], info["store_color"]) == (
        "1514875", "ADIDAS ORIGINALS", "IF6490", "marron/blanc",
    )
    # Lateral, tres cuartos, trasera y cenital: la 5.ª (foto puesta) no.
    assert [re.search(r"_(\d+)\.jpg", u).group(1) for u in detail.photo_urls] == ["101", "102", "104", "103"]
    assert all("sw=1200&sh=1200" in u for u in detail.photo_urls)
    assert detail.sizes[:2] == [{"name": "40 2/3", "in_stock": True}, {"name": "41 1/3", "in_stock": True}]
    assert detail.price_cents == 9000 and detail.store_color == "marron/blanc" and detail.store_data == {"model": "IF6490"}
    # De los cuatro enlaces de «Couleur», tres son esta zapatilla; el cuarto es otra (la de nobuk).
    assert [(s["product_ref"], s["name"]) for s in detail.siblings] == [
        ("courir:1514875", "Marron"), ("courir:1603583", "Argenté"), ("courir:1608473", "Beige"),
    ]
    assert "handball-spezial-nubuck-1608470" in _texto("courir_producto.html")
    assert detail.description.startswith("Redécouvrez un classique")
    assert courir.parse_product_page("<html>nada</html>") is None


def test_el_buscador_de_courir_entiende_enlaces_y_codigos_de_fabricante(monkeypatch):
    assert courir.parse_query("IF6490") == ("model", "IF6490")
    assert courir.parse_query("ref: dd1391-100") == ("model", "DD1391-100")
    assert courir.parse_query("1203A739-200") == ("model", "1203A739-200")
    assert courir.parse_query("https://www.courir.com/fr/p/adidas-originals-handball-spezial-1514875.html") == (
        "link", "/fr/p/adidas-originals-handball-spezial-1514875.html",
    )
    for otra in ("cazadora negra", "3918/300", "https://www.zara.com/fr/fr/x-p03918300.html"):
        with pytest.raises(NotThisStore):
            courir.parse_query(otra)
    with pytest.raises(SearchError, match="no es el de un producto"):
        courir.parse_query("https://www.courir.com/fr/c/homme/")

    asked = []

    def fake_get(self, url, accept=None, pause=None):
        asked.append(url)
        if "Search-UpdateGrid?q=IF4396" in url:
            return fetch.Page(200, _texto("courir_listado.html").encode())
        if "Search-UpdateGrid" in url:
            return fetch.Page(200, b"<div>nada</div>")
        return fetch.Page(200, _texto("courir_producto.html").encode())

    monkeypatch.setattr(courir.CourirConnector, "_get", fake_get)
    connector = courir.CourirConnector(pause=0)
    assert [(p.product_ref, p.brand) for p in connector.search("if4396", 12)] == [("courir:1609542", "Jordan")]
    with pytest.raises(SearchError, match="con el código XX9999"):
        connector.search("XX9999", 12)
    linked = connector.search("https://www.courir.com/fr/p/adidas-originals-handball-spezial-1514875.html", 12)
    assert [(p.name, p.brand, p.store_color, p.color, p.price_cents) for p in linked] == [
        ("Handball Spezial", "Adidas Originals", "marron/blanc", "marrón", 9000),
    ]
    # La ficha recién leída se recuerda: pedir su detalle no vuelve a llamar a la tienda.
    before = len(asked)
    assert connector.detail(linked[0].store_data).photo_urls and len(asked) == before


# ---------- JD Sports


def test_jd_sports_lee_el_listado_del_servidor_y_lo_ordena_por_novedad():
    data = _fixture("jd_listado.json")
    data["hits"].reverse()  # vienen en orden «recomendados»: el orden lo pone la antigüedad
    data["hits"].append({**data["hits"][0], "objectID": "1", "gender": ["Enfants"]})  # de niño: fuera
    data["hits"].append({**data["hits"][0], "objectID": "2", "name": "Nike Claquettes Victori"})  # chanclas: fuera
    products = jdsports.parse_listing(data, "baskets")
    assert [(p.product_ref, p.name, p.brand, p.store_color, p.color) for p in products] == [
        ("jdsports:19772886", "Cloudtilt", "On Running", "Noir", "negro"),
        ("jdsports:19713373", "Cloudtilt", "On Running", "Bleu", "azul"),
        ("jdsports:19615454", "Cloudtilt", "On Running", "Blanc", "blanco"),
    ]
    first = products[0]
    assert (first.price_cents, first.type, first.category) == (17000, "zapatillas", "calzado")
    assert first.url == "https://www.jdsports.fr/product/noir-on-running-cloudtilt/19772886_jdsportsfr/"
    assert jdsports.reference(first.store_data) == "807022"
    # Los datos salen del JSON de Next.js de la página (`searchServerState`).
    data_page = {"props": {"pageProps": {"searchServerState": {"initialResults": {"jd_prod_products_fr": {"results": [data]}}}}}}
    assert jdsports.listing_results(data_page)["nbHits"] == 1330
    with pytest.raises(ShopError, match="no era la esperada"):
        jdsports.listing_results({"props": {"pageProps": {}}})


def test_la_ficha_de_jd_sports_da_lateral_tres_cuartos_y_trasera():
    detail = jdsports.parse_product({"props": {"pageProps": {"product": _fixture("jd_producto.json")}}})
    assert [u.split("?")[0].rsplit("_", 1)[1] for u in detail.photo_urls] == ["a", "b", "c"]  # ni detalle ni suela
    assert detail.photo_urls[0].endswith("?w=1600&fmt=jpg&qlt=85")
    assert detail.price_cents == 17000 and detail.sizes[0] == {"name": "40", "in_stock": True}
    assert detail.composition.startswith("Tige : textile") and detail.store_data == {"ref": "807022"}
    assert len(detail.siblings) == 5 and detail.store_color == "Noir"
    assert jdsports.parse_product({"props": {"pageProps": {}}}) is None  # sin producto: ya no existe
    assert jdsports.parse_query("https://www.jdsports.fr/product/noir-on-running-cloudtilt/19772886_jdsportsfr/") == (
        "noir-on-running-cloudtilt", "19772886",
    )
    assert jdsports.parse_query("jdsports.es/product/x/19712004_jdsportses/") == ("x", "19712004")
    for otra in ("IF6490", "cazadora negra", "https://www.courir.com/fr/p/x-1514875.html"):
        with pytest.raises(NotThisStore):
            jdsports.parse_query(otra)


def test_una_tienda_que_bloquea_se_deja_en_paz_y_se_apunta_como_fallo(monkeypatch):
    monkeypatch.setattr(fetch.Fetcher, "get", _REAL_FETCHER_GET)
    answers = iter([fetch.Page(200, b"ok"), fetch.Page(403, b""), fetch.Page(403, b""), fetch.Page(200, b"ok")])
    calls = []

    def fake_httpx(self, url, headers):
        calls.append(url)
        return next(answers)

    monkeypatch.setattr(fetch.Fetcher, "_httpx", fake_httpx)
    fetcher = fetch.Fetcher("prueba", pause=0, timeout=5, accept_language="fr-FR")
    assert fetcher.get("https://t.test/1").status == 200
    with pytest.raises(ShopError, match="^HTTP 403$"):
        fetcher.get("https://t.test/2")
    with pytest.raises(ShopError, match="403 seguidos"):
        fetcher.get("https://t.test/3")
    with pytest.raises(ShopError, match="no se insiste"):
        fetcher.get("https://t.test/4")
    assert len(calls) == 3  # bloqueada: la cuarta ni sale

    # Un 429 o una página de comprobación bloquean a la primera.
    for page in (fetch.Page(429, b""), fetch.Page(403, b"<html>Just a moment... cf-chl</html>")):
        monkeypatch.setattr(fetch.Fetcher, "_httpx", lambda self, url, headers, page=page: page)
        other = fetch.Fetcher("prueba", pause=0, timeout=5, accept_language="fr-FR")
        with pytest.raises(ShopError, match="no se insiste"):
            other.get("https://t.test/x")


# ---------- Varias tiendas, la marca y la compra


def test_tres_tiendas_se_reparten_el_cupo_y_cada_una_tiene_su_filtro(client, tienda):
    tienda(camisas=[product(f"z{i}", "camisa", "negro") for i in range(6)])
    tienda(key="courir", name="Courir", camisas=[product(f"c{i}", "zapatillas", "blanco", store="courir") for i in range(6)])
    tienda(key="jdsports", name="JD Sports", camisas=[product(f"j{i}", "zapatillas", "negro", store="jdsports")
                                                      for i in range(6)])
    _refresh(limit=6)
    assert sorted(i.store for i in _items("nuevo")) == ["courir", "courir", "jdsports", "jdsports", "zara", "zara"]
    for key in ("zara", "courir", "jdsports"):
        filtered = client.get("/api/shop/next", params={"store": key}).json()
        assert filtered["item"]["store"] == key and filtered["remaining"] == 2 and filtered["more"] == 4
    # «Ver más» sin filtro: otra vez a partes iguales.
    assert _more(limit=3)["added"] == 3
    assert [i.store for i in _items("nuevo")].count("jdsports") == 3


def _calzado(ref, brand, store="courir", color="blanco") -> ShopProduct:
    shoe = product(ref, "zapatillas", color, store=store, section="camisas")
    shoe.brand = brand
    return shoe


def test_la_marca_se_guarda_se_ensena_y_se_aprende_por_familias(client, tienda):
    tienda(key="courir", name="Courir", camisas=[
        _calzado("n1", "Nike"), _calzado("n2", "Nike"), _calzado("a1", "Adidas Originals"), _calzado("a2", "Adidas"),
        _calzado("n3", "Nike"), _calzado("a3", "Adidas Originals"),
    ])
    _refresh(limit=20)
    items = {i.product_ref: i for i in _items("nuevo")}
    assert items["courir:a1"].brand == "Adidas Originals"
    out = client.get("/api/shop/next").json()["item"]
    assert out["brand"] in ("Nike", "Adidas", "Adidas Originals") and out["store_name"] == "Courir"

    for ref in ("courir:n1", "courir:n2"):
        client.post(f"/api/shop/items/{items[ref].id}/like")
    for ref in ("courir:a1", "courir:a2"):
        client.post(f"/api/shop/items/{items[ref].id}/dislike")
    taste = _taste()
    assert set(taste.brands) == {"Nike", "Adidas"}  # Adidas Originals cuenta como Adidas
    with SessionLocal() as db:
        nike, adidas = db.get(ShopItem, items["courir:n3"].id), db.get(ShopItem, items["courir:a3"].id)
        nike_score, nike_reasons = shopping.score(nike, [], None, taste)
        adidas_score, _ = shopping.score(adidas, [], None, taste)
        nike.brand = None
        neutral, _ = shopping.score(nike, [], None, taste)
        db.rollback()
    assert "Te suelen gustar las Nike" in _texts(nike_reasons)
    assert nike_score > neutral > adidas_score
    # Pesa menos que el tipo y el color.
    assert shopping.W_PREF_BRAND < shopping.W_PREF_TYPE and shopping.W_PREF_BRAND < shopping.W_PREF_COLOR


def test_al_comprar_unas_zapatillas_la_marca_es_la_suya_y_la_tienda_va_aparte(client, tienda, analyzers):
    shoe = _calzado("n1", "Nike")
    shoe.store_color = ""  # como en Courir: el listado no dice el color
    connector = tienda(key="courir", name="Courir", camisas=[shoe])
    connector.details["n1"] = ShopDetail(
        price_cents=None, sizes=[{"name": "42", "in_stock": True}],
        photo_urls=[f"https://fotos.test/n1_10{n}.jpg" for n in (1, 2, 4, 3)], store_color="Noir/Blanc",
        store_data={"model": "DD1391-100"},
    )
    _refresh(limit=4)
    [item] = _items("nuevo")
    # El color sale de la ficha cuando el listado no lo traía; y la ficha añade el código de fabricante.
    assert (item.store_color, item.color, item.store_data["model"]) == ("Noir/Blanc", "negro", "DD1391-100")
    assert len(item.photos) == 4
    analyzers(FakeAnalyzer("codex", json.dumps(VALID_DRAFT)), FakeAnalyzer("claude"))
    bought = client.post(f"/api/shop/items/{item.id}/bought", json={"size": "42"}).json()
    garment = client.get(f"/api/garments/{bought['garment_id']}").json()
    assert (garment["brand"], garment["store_name"]) == ("Nike", "Courir")
    assert not storage.exists(item.photos[3])  # la cuarta foto solo era para el visor


def test_lo_elegido_con_las_categorias_de_zara_espana_sigue_valiendo_en_francia(client):
    with SessionLocal() as db:
        shopping._set(db, shopping.K_CATEGORIES, {"zara": ["hombre-camisas-l737", "hombre-jeans-l659"]})
        db.commit()
        assert shopping.active_categories(db, "zara") == ["homme-chemises-l737", "homme-jeans-l659"]


# ---------- Traducción al español


class FakeTranslator:
    """Traduce poniendo «ES:» delante; o devuelve (o lanza) lo que se le diga."""

    def __init__(self, answer=None):
        self.calls: list[list[str]] = []
        self.answer = answer

    def __call__(self, prompt):
        texts = json.loads(prompt.split("Textos (JSON):", 1)[1])
        self.calls.append(texts)
        if isinstance(self.answer, Exception):
            raise self.answer
        if self.answer is not None:
            return json.dumps({"traducciones": self.answer})
        return json.dumps({"traducciones": [f"ES: {t}" for t in texts]})


def _tienda_francesa(tienda, n=3):
    connector = tienda(camisas=[product(f"f{i}", "sudadera", "gris", name=f"Sweat à capuche {i}") for i in range(n)])
    connector.language = "fr"
    connector.details.update({
        f"f{i}": ShopDetail(price_cents=None, sizes=[{"name": "M", "in_stock": True}],
                            photo_urls=[f"https://fotos.test/f{i}.jpg"], composition="Coton 100%")
        for i in range(n)
    })
    return connector


def test_lo_que_se_ensena_se_traduce_en_lote_y_se_guarda_el_original(client, tienda, monkeypatch):
    _tienda_francesa(tienda)
    _refresh(limit=3)
    fake = FakeTranslator()
    monkeypatch.setattr(traductor, "BACKENDS", [("codex", fake)])
    with SessionLocal() as db:
        assert shopping.translate_items(db) == 3
    # Una sola llamada con todos los textos, sin repetidos (el color y la composición son los mismos).
    assert len(fake.calls) == 1 and len(fake.calls[0]) == 5
    item = client.get("/api/shop/next").json()["item"]
    assert item["name"].startswith("ES: Sweat à capuche") and item["name_original"].startswith("Sweat à capuche")
    assert (item["store_color"], item["composition"]) == ("ES: Gris", "ES: Coton 100%")
    with SessionLocal() as db:
        row = db.get(ShopItem, item["id"])
        assert row.name.startswith("Sweat à capuche") and row.store_color == "Gris"  # lo original sigue ahí
        # No se traduce dos veces.
        assert shopping.translate_items(db) == 0 and len(fake.calls) == 1
    # Los candidatos (sin fotos) no se traducen.
    assert all(not i.translated for i in _items("candidato"))


def test_una_traduccion_que_no_cuadra_o_que_falla_deja_el_original(client, tienda, monkeypatch):
    _tienda_francesa(tienda, 2)
    _refresh(limit=2)
    monkeypatch.setattr(traductor, "BACKENDS", [("codex", FakeTranslator(answer=["Solo una"]))])
    with SessionLocal() as db:
        assert shopping.translate_items(db) == 0
    assert all(i.name_es is None and not i.translated for i in _items("nuevo"))
    # Si Codex falla, prueba Claude; si fallan los dos, se queda en francés y se reintenta otro día.
    codex, claude = FakeTranslator(answer=AnalysisError("sin sesión")), FakeTranslator(answer=AnalysisError("sin clave"))
    monkeypatch.setattr(traductor, "BACKENDS", [("codex", codex), ("claude", claude)])
    with SessionLocal() as db:
        assert shopping.translate_items(db) == 0
    assert len(codex.calls) == 1 and len(claude.calls) == 1
    item = client.get("/api/shop/next").json()["item"]
    assert item["name"].startswith("Sweat à capuche") and item["name_original"] is None
    # Con Claude funcionando, el plan B traduce.
    monkeypatch.setattr(traductor, "BACKENDS", [("codex", codex), ("claude", FakeTranslator())])
    with SessionLocal() as db:
        assert shopping.translate_items(db) == 2


def test_la_nota_no_cambia_con_la_traduccion(client, tienda, monkeypatch):
    _tienda_francesa(tienda, 2)
    _refresh(limit=2)
    before = {i.id: (i.score, i.reasons) for i in _items("nuevo")}
    monkeypatch.setattr(traductor, "BACKENDS", [("codex", FakeTranslator())])
    with SessionLocal() as db:
        shopping.translate_items(db)
        shopping.rescore_pending(db)
    assert {i.id: (i.score, i.reasons) for i in _items("nuevo")} == before


def test_una_tienda_en_espanol_no_se_traduce(client, tienda, monkeypatch):
    tienda(camisas=[product("a")])
    _refresh(INVIERNO)
    fake = FakeTranslator()
    monkeypatch.setattr(traductor, "BACKENDS", [("codex", fake)])
    with SessionLocal() as db:
        assert shopping.translate_items(db) == 0
    assert fake.calls == []


def test_las_columnas_de_marca_y_traduccion_se_anaden_a_una_base_de_datos_anterior():
    from sqlalchemy import create_engine

    from app import db as database

    old = create_engine("sqlite://")
    with old.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE shop_items (id INTEGER PRIMARY KEY, status VARCHAR(20))")
    original, database.engine = database.engine, old
    try:
        database._add_missing_columns()
    finally:
        database.engine = original
    with old.begin() as conn:
        assert {"brand", "name_es", "store_color_es", "composition_es", "translated"} <= {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(shop_items)")
        }
