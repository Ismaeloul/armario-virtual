"""Compras (Fase 4). Todo sin red: un conector falso y JSON de ejemplo recortado de Zara."""
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from conftest import VALID_DRAFT, FakeAnalyzer
from sqlalchemy import select

from app import catalog
from app.db import SessionLocal
from app.main import referenced_photos
from app.models import Garment, ShopItem, now_utc
from app.services import outfits, shopping, shops, storage
from app.services.ai.base import AnalysisError
from app.services.shops import NotThisStore, SearchError, ShopDetail, ShopError, ShopProduct, estimate, zara

FIXTURES = Path(__file__).parent / "fixtures"
INVIERNO, VERANO = date(2026, 11, 18), date(2026, 7, 1)  # miércoles los dos
VIERNES = date(2026, 11, 20)


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def product(ref: str, type: str = "camisa", color: str = "blanco", price: int = 2995, section: str = "camisas",
            store: str = "zara", **extra) -> ShopProduct:
    return ShopProduct(
        store=store, product_ref=f"{store}:{ref}", name=extra.pop("name", f"{type.capitalize()} {ref}"),
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

    def __init__(self, photo: bytes, key: str = "zara", name: str = "Zara", **by_section: list[ShopProduct]):
        self.key, self.name = key, name
        self.photo = photo
        self.products = by_section
        self.failing: set[str] = set()  # categorías que fallan
        self.gone: set[str] = set()  # productos que ya no existen
        self.details: dict[str, ShopDetail] = {}
        self.calls: list[tuple[str, str]] = []
        self.found: dict[str, list[ShopProduct] | Exception] = {}  # lo que da el buscador con cada texto
        self.family: dict[str, list[dict]] = {}  # producto -> los colores en los que existe (ver `_colores`)

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
            siblings=self.family.get(ref),
        )

    def reference(self, store_data):
        return store_data.get("reference")

    def download(self, url):
        self.calls.append(("foto", url))
        return self.photo

    def search(self, query, limit):
        self.calls.append(("busca", query))
        answer = self.found.get(query, SearchError("No he encontrado nada con esa referencia"))
        if isinstance(answer, Exception):
            raise answer
        return answer[:limit]

    def asked(self, kind: str) -> list[str]:
        return [what for k, what in self.calls if k == kind]


@pytest.fixture
def tienda(monkeypatch, photo_bytes):
    """Instala la tienda falsa y la deja activada."""

    def install(key: str = "zara", name: str = "Zara", **by_section) -> FakeConnector:
        connector = FakeConnector(photo_bytes, key, name, **by_section)
        monkeypatch.setitem(shops.CONNECTORS, key, connector)
        with SessionLocal() as db:
            shopping.set_store(db, key, True, None)
        return connector

    return install


def _refresh(today: date = INVIERNO, **kwargs) -> dict:
    with SessionLocal() as db:
        return shopping.refresh(db, today=today, **kwargs)


def _items(status: str | None = None) -> list[ShopItem]:
    """Lo que se ha enseñado alguna vez (o, si se pide, lo de un estado; «candidato» incluido)."""
    with SessionLocal() as db:
        stmt = select(ShopItem).order_by(ShopItem.id)
        return list(db.scalars(stmt.where(ShopItem.status == status if status else ShopItem.status != "candidato")))


def _more(today: date = INVIERNO, **kwargs) -> dict:
    with SessionLocal() as db:
        return shopping.more(db, today=today, **kwargs)


def _taste() -> shopping.ShopTaste:
    with SessionLocal() as db:
        return shopping.load_shop_taste(db)


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
    assert first.url == "https://www.zara.com/fr/fr/sobrecamisa-estructura-brillo-p05854122.html?v1=590649460"
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
    assert first.url == "https://www.zara.com/fr/fr/sobrecamisa-estructura-brillo-p05854122.html?v1=590649460"


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
        ("Azul", "azul"), ("Verde botella", "verde"), ("Mostaza", "amarillo"),
        # Sin palabra conocida ni tono: desconocido (""), no «multicolor» (no debe restar al ordenar).
        ("Color raro", ""), ("Multicolor", "multicolor"),
    ],
)
def test_el_color_de_la_tienda_se_pasa_a_la_paleta(store_color, expected):
    assert estimate.estimate_color(store_color) == expected
    assert expected in catalog.COLORS or expected == estimate.UNKNOWN_COLOR


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


# Un armario de diario: mucho negro, gris y azul, nada de colores fuertes.
ARMARIO = [
    _item(1, "vaquero", "azul"), _item(2, "vaquero", "negro"), _item(3, "chino", "beige"),
    _item(4, "pantalón", "negro"), _item(5, "pantalón", "gris"), _item(6, "camiseta", "blanco"),
    _item(7, "camiseta", "negro"), _item(8, "camiseta", "gris"), _item(9, "jersey", "gris", season="invierno"),
    _item(10, "sudadera", "negro", season="invierno"), _item(11, "chaqueta", "negro"),
    _item(12, "zapatillas", "blanco"), _item(13, "zapatillas", "negro"), _item(14, "vaquero", "azul"),
    _item(15, "vaquero", "negro"), _item(16, "chino", "azul marino"),
]


def _texts(reasons: list[dict], kind: str | None = None) -> list[str]:
    return [m["text"] for m in reasons if kind in (None, m["kind"])]


def test_sin_valoraciones_un_basico_neutro_gana_a_una_pieza_llamativa():
    basico, motivos = shopping.score(product("a", "jersey", "negro", name="Jersey básico cuello redondo"), ARMARIO)
    assert "Es un color que ya llevas (negro)" in _texts(motivos) and not _texts(motivos, "contra")

    # Lo que el usuario vio en la primera versión: todo eso queda ahora por debajo de lo básico.
    raros = {
        "Jersey cropped": product("b", "jersey", "rosa", name="Jersey cropped"),
        "Pantalón culotte": product("c", "pantalón", "negro", name="Pantalón culotte pliegues"),
        "Jeans blancos": product("d", "vaquero", "blanco", name="Jeans straight fit"),
        "Zapatilla amarilla": product("e", "zapatillas", "amarillo", name="Zapatilla retro"),
        "Camisa de flores": product("f", "camisa", "verde", name="Camisa estampado floral", pattern="gráfico"),
    }
    notas = {nombre: shopping.score(p, ARMARIO) for nombre, p in raros.items()}
    assert all(nota < basico - 10 for nota, _ in notas.values()), notas
    assert {"No llevas nada rosa", "Corte poco habitual (cropped)"} <= set(_texts(notas["Jersey cropped"][1], "contra"))
    assert "Corte poco habitual (culotte)" in _texts(notas["Pantalón culotte"][1], "contra")
    assert "No tienes pantalones en blanco" in _texts(notas["Jeans blancos"][1], "contra")  # blanco arriba sí, abajo no
    assert "No llevas nada amarillo" in _texts(notas["Zapatilla amarilla"][1], "contra")
    assert {"No llevas nada verde", "No llevas nada con dibujo"} <= set(_texts(notas["Camisa de flores"][1], "contra"))


def test_los_huecos_del_armario_solo_desempatan():
    # Que falte el tipo ya no compensa un color que no lleva: «no tienes ninguna sobrecamisa rosa» no vende.
    rosa, motivos = shopping.score(product("a", "sobrecamisa", "rosa"), ARMARIO)
    repetida, _ = shopping.score(product("b", "camiseta", "negro"), ARMARIO)
    assert "No tienes ninguna sobrecamisa" in _texts(motivos) and repetida > rosa
    assert "No tienes ningún jersey rosa" not in _texts(shopping.score(product("c", "jersey", "rosa"), ARMARIO)[1])

    # Entre dos prendas igual de ponibles, sí: gana la que tapa un hueco, y por poco.
    hueco, motivos = shopping.score(product("d", "sobrecamisa", "negro"), ARMARIO)
    otra_mas, contra = shopping.score(product("e", "chaqueta", "negro"), ARMARIO)
    assert {"No tienes ninguna sobrecamisa", "Solo tienes 1 chaqueta o abrigo"} <= set(_texts(motivos))
    assert "Ya tienes 1 chaqueta negra" in _texts(contra, "contra")
    assert 0 < hueco - otra_mas <= shopping.GAP_TYPE - shopping.DUPLICATE
    _, motivos = shopping.score(product("f", "botas", "marrón"), ARMARIO)
    assert {"No tienes botas", "Solo tienes 2 pares de zapatos"} <= set(_texts(motivos))
    _, motivos = shopping.score(product("g", "camiseta", "azul marino"), ARMARIO)
    assert "No tienes ninguna camiseta azul marino" in _texts(motivos)  # un color base sí es un hueco

    # Los pesos, por bloques: los gustos mandan, luego parecerse a lo que lleva, y los huecos al final.
    gustos = shopping.W_PREF_TYPE + shopping.W_PREF_COLOR + shopping.W_PREF_WORD + shopping.W_PREF_PRICE
    parecido = shopping.W_MATCH + shopping.W_PALETTE + shopping.W_BASIC
    huecos = shopping.GAP_TYPE + shopping.GAP_COLOR + shopping.GAP_CATEGORY
    assert gustos > parecido > 3 * huecos
    assert huecos < min(shopping.W_PALETTE, shopping.W_MATCH, shopping.W_PREF_TYPE, shopping.W_PREF_COLOR)
    assert huecos < -shopping.OFF_PALETTE and huecos < -shopping.RISKY


def test_la_nota_penaliza_repetir_lo_que_ya_hay():
    wardrobe = [_item(1, "vaquero", "azul"), _item(2, "sudadera", "negro"), _item(3, "sudadera", "negro"),
                _item(4, "sudadera", "negro"), _item(5, "sudadera", "gris"), _item(6, "zapatillas", "blanco")]

    repetida, motivos = shopping.score(product("a", "sudadera", "negro"), wardrobe)
    assert _texts(motivos, "contra") == ["Ya tienes 3 sudaderas negras"]
    una_vez, motivos = shopping.score(product("c", "sudadera", "gris"), wardrobe)
    assert "Ya tienes 1 sudadera gris" in _texts(motivos)
    _, motivos = shopping.score(product("b", "sudadera", "verde oliva"), wardrobe)
    assert "No tienes ninguna sudadera verde oliva" in _texts(motivos)
    assert una_vez > repetida


def test_lo_que_dice_en_la_tienda_pesa_mas_que_todo_lo_demas():
    basico = product("a", "jersey", "negro", name="Jersey básico cuello redondo")
    llamativo = product("b", "jersey", "rosa", name="Jersey cropped")
    sin_gustos = shopping.ShopTaste()
    assert shopping.score(basico, ARMARIO, prefs=sin_gustos)[0] > shopping.score(llamativo, ARMARIO, prefs=sin_gustos)[0]

    # El usuario se queda con lo rosa y cropped y descarta los básicos negros: el orden se da la vuelta.
    prefs = shopping.ShopTaste()
    for _ in range(4):
        prefs.learn(product("x", "jersey", "rosa", name="Jersey cropped punto"), liked=True)
        prefs.learn(product("y", "jersey", "negro", name="Jersey básico"), liked=False, reason="color")
    gusta, motivos = shopping.score(llamativo, ARMARIO, prefs=prefs)
    assert gusta > shopping.score(basico, ARMARIO, prefs=prefs)[0]
    assert {"Te suele gustar el rosa", "Te suele gustar lo «cropped»"} <= set(_texts(motivos, "pro"))
    assert "Corte poco habitual (cropped)" not in _texts(motivos)  # ya ha dicho que le gusta


def test_las_palabras_del_nombre_se_aprenden():
    assert shopping.name_words("Pantalón relaxed fit PANA") == {"relaxed", "pana"}  # ni el tipo ni el relleno
    assert shopping.name_words("Jerséis de algodón básicos") == {"algodon", "basicos"}  # sin tildes
    assert shopping.name_words("Top crochet") == {"top", "crochet"}  # las de tres letras también cuentan

    wardrobe = [_item(1, "vaquero", "azul"), _item(2, "camisa", "blanco")]
    prefs = shopping.ShopTaste()
    for i in range(3):
        prefs.learn(product(f"x{i}", "pantalón", "marrón", name="Pantalón pana relaxed fit"), liked=True)
    for i in range(25):  # un descarte cuenta poco: hace falta repetirlo mucho para que sea una preferencia
        prefs.learn(product(f"y{i}", "vaquero", "azul", name="Jeans skinny fit"), liked=False)
    assert prefs.opinion(prefs.words, "pana") > 0 > prefs.opinion(prefs.words, "skinny")
    assert "pantalon" not in prefs.words and "fit" not in prefs.words

    # Otro tipo, otro color y otro precio: lo único en común es la palabra.
    pana = product("a", "sobrecamisa", "verde oliva", price=5995, name="Sobrecamisa pana")
    lisa = product("b", "sobrecamisa", "verde oliva", price=5995, name="Sobrecamisa algodón")
    con_pana, motivos = shopping.score(pana, wardrobe, prefs=prefs)
    assert con_pana > shopping.score(lisa, wardrobe, prefs=prefs)[0]
    assert "Te suele gustar lo «pana»" in _texts(motivos, "pro")
    skinny, motivos = shopping.score(product("c", "chino", "beige", price=5995, name="Chino skinny"), wardrobe, prefs=prefs)
    assert "Sueles descartar lo «skinny»" in _texts(motivos, "contra")
    assert skinny < shopping.score(product("d", "chino", "beige", price=5995, name="Chino recto"), wardrobe, prefs=prefs)[0]

    # Un corte raro resta de entrada (el «top», también) y deja de restar cuando el usuario lo acepta.
    cropped = product("e", "camiseta", "blanco", name="Camiseta cropped")
    normal = product("f", "camiseta", "blanco", name="Camiseta algodón")
    antes, motivos = shopping.score(cropped, wardrobe, prefs=shopping.ShopTaste())
    assert "Corte poco habitual (cropped)" in _texts(motivos, "contra")
    assert shopping.score(normal, wardrobe)[0] - antes == -shopping.RISKY
    assert "Corte poco habitual (top)" in _texts(shopping.score(product("g", "camiseta", "negro", name="Top canalé"), wardrobe)[1])
    prefs.learn(product("h", "sudadera", "gris", name="Sudadera cropped"), liked=True)
    assert "Corte poco habitual (cropped)" not in _texts(shopping.score(cropped, wardrobe, prefs=prefs)[1])


@pytest.mark.parametrize(
    ("motivo", "esperado"),
    [
        (None, {"types": -0.2, "colors": -0.2, "prices": -0.2, "words": -0.2}),  # repartido y muy flojo
        ("estilo", {"types": -0.5, "words": -1.0}),  # las palabras del nombre y, algo, el tipo
        ("color", {"colors": -1.0}),
        ("caro", {"prices": -1.0}),
        ("ya_tengo", {}),  # no dice nada de sus gustos
    ],
)
def test_el_motivo_del_descarte_decide_a_que_se_le_carga_la_culpa(motivo, esperado):
    prefs = shopping.ShopTaste()
    prefs.learn(product("x", "polo", "rosa", price=1995, name="Polo cropped"), liked=False, reason=motivo)
    aprendido = {
        tabla: next(iter(getattr(prefs, tabla).values()))[0]
        for tabla in ("types", "colors", "prices", "words") if getattr(prefs, tabla)
    }
    assert aprendido == esperado
    assert set(prefs.types) <= {"polo"} and set(prefs.colors) <= {"rosa"} and set(prefs.words) <= {"cropped"}

    # Un «me gusta» cuenta entero en todo.
    prefs = shopping.ShopTaste()
    prefs.learn(product("x", "polo", "rosa", price=1995, name="Polo cropped"), liked=True)
    assert [t["polo" if i == 0 else k][0] for i, (t, k) in enumerate(
        [(prefs.types, ""), (prefs.colors, "rosa"), (prefs.prices, "hasta_25"), (prefs.words, "cropped")])] == [1.0] * 4


def test_la_nota_aprende_de_los_me_gusta_de_la_tienda():
    wardrobe = [_item(1, "vaquero", "azul"), _item(2, "camisa", "blanco")]
    prefs = shopping.ShopTaste()
    for _ in range(4):
        prefs.learn(product("x", "sobrecamisa", "negro", price=4995), liked=True)
    for _ in range(25):  # los descartes pesan poco y solo cuentan al acumularse
        prefs.learn(product("y", "polo", "rosa", price=1995), liked=False)

    gusta, motivos = shopping.score(product("a", "sobrecamisa", "negro", price=3995), wardrobe, prefs=prefs)
    neutra, _ = shopping.score(product("a", "sobrecamisa", "negro", price=3995), wardrobe, prefs=shopping.ShopTaste())
    texts = [m["text"] for m in motivos]
    assert gusta > neutra
    assert "Te suelen gustar las sobrecamisas" in texts and "Te suele gustar el negro" in texts

    no_gusta, motivos = shopping.score(product("b", "polo", "rosa", price=1995), wardrobe, prefs=prefs)
    sin_opinion, _ = shopping.score(product("b", "polo", "rosa", price=1995), wardrobe, prefs=shopping.ShopTaste())
    assert no_gusta < sin_opinion
    assert {"Sueles descartar los polos", "Sueles descartar el rosa"} <= {
        m["text"] for m in motivos if m["kind"] == "contra"
    }


def test_fuera_de_mayo_a_septiembre_no_se_propone_ropa_de_verano():
    bermuda = product("a", "pantalón corto", "beige", season="verano")
    camiseta = product("b", "camiseta", "blanco")
    manga_larga = product("c", "camiseta", "blanco", details="camiseta manga larga")
    assert [shopping.out_of_season(p, INVIERNO) for p in (bermuda, camiseta, manga_larga)] == [True, True, False]
    assert not any(shopping.out_of_season(p, VERANO) for p in (bermuda, camiseta, manga_larga))

    # El nombre y la descripción también cuentan: un jersey «de invierno» de manga corta, una camisa de lino…
    jersey = product("d", "jersey", "negro", season="invierno", details="jersey punto. Cuello redondo y manga corta.")
    lino = product("e", "camisa", "beige", name="Camisa relaxed fit 100% lino")
    tirantes = product("f", "camisa", "blanco", details="camisa. Tejido principal: lino.")
    normal = product("g", "camisa", "blanco", details="camisa oxford. Cuello abotonado y manga larga con puños.")
    assert [shopping.out_of_season(p, INVIERNO) for p in (jersey, lino, tirantes, normal)] == [True, True, True, False]
    assert not any(shopping.out_of_season(p, VERANO) for p in (jersey, lino, tirantes))
    assert shopping.summer_text("Camiseta de TIRANTES") and shopping.summer_text("Chaleco sin mangas")
    assert not shopping.summer_text("Sobrecamisa de pana con forro") and not shopping.summer_text(None)
    # Visto en Zara: el nombre dice manga larga y la descripción, copiada de otra, manga corta. Manda el nombre.
    liosa = product("h", "camiseta", "negro", details="camiseta manga larga relaxed fit. Cuello redondo y manga corta.")
    assert not shopping.summer_text(liosa.details) and not shopping.out_of_season(liosa, INVIERNO)


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
        # Nunca consultada: toca la primera noche después de activarla (aquí, el miércoles a las 15:00).
        shopping._set(db, shopping.K_ENABLED_AT, {"zara": "2026-11-18T14:00:00+00:00"})
        db.commit()
        noche = datetime(2026, 11, 19, 3, 30)
        assert not shopping.is_due(db, "zara", now=datetime(2026, 11, 18, 23, 0))
        assert shopping.is_due(db, "zara", now=noche) and shopping.due_stores(db, now=noche) == ["zara"]
        assert shopping.next_check(db, "zara", INVIERNO) == INVIERNO + timedelta(days=1)

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
    # Las tiendas reales arrancan desactivadas, cada una con su día de consulta.
    assert [(s["key"], s["name"], s["enabled"], s["weekday"]) for s in state["stores"]] == [
        ("zara", "Zara", False, 4), ("courir", "Courir", False, 1), ("jdsports", "JD Sports", False, 2),
        ("pullandbear", "Pull&Bear", False, 0), ("bershka", "Bershka", False, 3),
        ("massimodutti", "Massimo Dutti", False, 1), ("lefties", "Lefties", False, 5), ("nike", "Nike", False, 3),
        ("jackjones", "Jack & Jones", False, 0), ("carhartt", "Carhartt WIP", False, 2),
        ("snipes", "Snipes", False, 5), ("size", "size?", False, 6), ("footlocker", "Foot Locker", False, 4),
        ("jules", "Jules", False, 2), ("bonobo", "Bonobo", False, 4), ("uniqlo", "Uniqlo", False, 0),
        ("mango", "Mango", False, 1), ("hm", "H&M", False, 3), ("cos", "COS", False, 5),
        ("weekday", "Weekday", False, 6),
    ]
    assert [s["weekday_after_release"] for s in state["stores"]] == [False] * 20  # el falso no lo dice
    assert [s["browser"] for s in state["stores"]] == [False, False, True, True, True, True, True, False, False, False,
                                                       True, True, False, True, True] + [True] * 5
    assert [s["key"] for s in state["stores"] if s["heavy"]] == [
        "pullandbear", "bershka", "massimodutti", "lefties", "jules", "bonobo", "uniqlo", "mango", "hm", "cos",
        "weekday"]
    # El reparto de la semana, de lunes a domingo, y su tope por noche.
    assert state["week"] == [
        ["pullandbear", "jackjones", "uniqlo"], ["courir", "massimodutti", "mango"], ["jdsports", "carhartt", "jules"],
        ["bershka", "nike", "hm"], ["zara", "footlocker", "bonobo"], ["lefties", "snipes", "cos"], ["size", "weekday"],
    ]
    assert (state["per_night"], state["heavy_per_night"]) == (3, 2)
    assert all(c["enabled"] for c in state["stores"][0]["categories"])
    assert state["running"] is False and state["pending"] == 0
    assert state["stores"][0]["weekday"] == 4 and state["stores"][0]["next_check"] is None
    assert state["stores"][0]["status"] == {
        "state": "never", "at": None, "found": 0, "added": 0, "failed": 0, "error": None, "complete": False,
        "cancelled": False, "sections": 0, "sections_total": 0, "pages": 0, "seconds": 0, "resume": False,
    }
    assert client.post("/api/shop/refresh").status_code == 409  # sin tienda activada no hay tanda
    assert client.post("/api/shop/refresh", json={"store": "zara"}).status_code == 409
    assert client.post("/api/shop/refresh", json={"store": "otra"}).status_code == 404
    assert client.get("/api/shop/next").json() == {
        "item": None, "remaining": 0, "more": 0, "can_undo": False, "refilling": False, "queue": [],
    }
    assert state["last_more"] is None and client.post("/api/shop/more").status_code == 409
    with SessionLocal() as db:
        assert shopping.due_stores(db) == []

    state = client.patch("/api/shop/settings", json={"store": "zara", "enabled": True, "categories": ["camisas"]}).json()
    assert state["stores"][0]["enabled"] is True
    assert [c["slug"] for c in state["stores"][0]["categories"] if c["enabled"]] == ["camisas"]
    assert client.patch("/api/shop/settings", json={"store": "otra", "enabled": True}).status_code == 404
    with SessionLocal() as db:
        # Recién activada: toca la primera noche, a las 03:30 (con «Consultar ahora», ya).
        moment = shopping.due_at(db, "zara")
        assert moment.strftime("%H:%M") == "03:30" and moment > shopping.local_now()
        assert shopping.due_stores(db) == [] and shopping.due_stores(db, now=moment) == ["zara"]

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
    assert after_dislike["remaining"] == 1 and after_dislike["can_undo"] is True
    assert client.get(disliked["photos"][0]["url"]).status_code == 200  # por si se deshace con «Volver»

    liked = client.get("/api/shop/liked").json()
    assert [i["id"] for i in liked] == [item["id"]]
    assert liked[0]["status"] == "gustado" and liked[0]["expires_soon"] is False and liked[0]["expires_at"]
    state = client.get("/api/shop/state").json()
    assert (state["pending"], state["liked"]) == (1, 1)

    # Quitar de «Me gustan»: pasa a descartado, no vuelve y sus fotos se borran (eso no se deshace).
    assert client.delete(f"/api/shop/items/{item['id']}").status_code == 204
    assert client.get("/api/shop/liked").json() == []
    assert client.get(item["photos"][0]["url"]).status_code == 404
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


def _zara_pages(pages: int) -> dict:
    """Un listado de Zara con `pages` páginas juntas (una «Camisa» por página, para contarlas)."""
    items = [
        {"type": "Product", "name": f"CAMISA {n}", "price": 2995,
         "seo": {"keyword": f"camisa-{n}", "seoProductId": f"0{n:07d}", "discernProductId": n},
         "detail": {"colors": [{"id": "800", "name": "BLANCO"}]}}
        for n in range(1, pages + 1)
    ]
    return {"productGroups": [{"elements": [{"commercialComponents": items}]}]}


@pytest.mark.parametrize(("existen", "pedidas"), [
    (3, ["page=4", "page=2", "page=3"]),  # se pasa (404), busca a medio camino
    (11, ["page=4", "page=8", "page=16", "page=12", "page=10", "page=11"]),
    (1, ["page=4", "page=2", ""]),  # solo la primera: sin `page`
])
def test_zara_lee_la_categoria_entera_doblando_paginas(monkeypatch, existen, pedidas):
    """`page=N` trae las N primeras juntas y dice si es la última; pedir de más da 404. Se dobla y, si se
    pasa, se busca a medio camino: la categoría entera con pocas peticiones."""
    connector = zara.ZaraConnector(pause=0)
    asked = []

    def fake_json(url, *args, **kwargs):
        match = re.search(r"page=(\d+)", url)
        pages = int(match.group(1)) if match else 1
        asked.append(match.group() if match else "")
        if pages > existen:
            return None
        return {**_zara_pages(pages), "paginationInfo": {"page": pages, "isLastPage": pages == existen}}

    monkeypatch.setattr(connector, "_json", fake_json)
    products = connector.list_category("hombre-camisas-l737")
    assert asked == pedidas and len(products) == existen


def test_zara_respeta_el_tope_y_guarda_lo_leido_si_falla_a_mitad(monkeypatch):
    connector = zara.ZaraConnector(pause=0)
    asked = []

    def fake_json(url, *args, **kwargs):
        pages = int(re.search(r"page=(\d+)", url).group(1))
        asked.append(pages)
        if pages > 4:
            raise ShopError("HTTP 500")
        return {**_zara_pages(pages), "paginationInfo": {"page": pages, "isLastPage": False}}

    monkeypatch.setattr(connector, "_json", fake_json)
    with pytest.raises(shops.Partial) as caught:
        connector.list_category("hombre-camisas-l737")
    assert asked == [4, 8] and len(caught.value.products) == 4 and "HTTP 500" in str(caught.value.cause)
    # Con un tope de 6 páginas no se pasa de ahí aunque la tienda diga que hay más.
    monkeypatch.setenv("ARMARIO_SHOP_MAX_PAGES_ZARA", "6")
    monkeypatch.setattr(connector, "_json", lambda url, *a, **k: {
        **_zara_pages(int(re.search(r"page=(\d+)", url).group(1))), "paginationInfo": {"isLastPage": False}})
    assert len(connector.list_category("hombre-camisas-l737")) == 6


# ---------- Candidatos y «Ver más»


def test_la_consulta_guarda_todo_el_catalogo_como_candidatos_y_los_renueva(client, tienda):
    connector = tienda(camisas=[product(f"c{i}") for i in range(5)])
    _refresh(limit=2)
    assert len(_items("nuevo")) == 2
    candidatos = _items("candidato")
    assert len(candidatos) == 3 and all(c.photos == [] and c.sizes == [] for c in candidatos)  # sin fotos ni ficha
    assert client.get("/api/shop/state").json()["pending"] == 2  # los candidatos no son propuestas

    # Una semana después la tienda ha retirado uno, ha cambiado el precio de otro y trae uno nuevo.
    retirado, rebajado = candidatos[0].product_ref, candidatos[1].product_ref
    connector.products["camisas"] = [
        p for p in connector.products["camisas"] if p.product_ref != retirado
    ] + [product("nuevo")]
    next(p for p in connector.products["camisas"] if p.product_ref == rebajado).price_cents = 1995
    _refresh(today=INVIERNO + timedelta(days=7), limit=1)
    with SessionLocal() as db:
        refs = {i.product_ref: i for i in db.scalars(select(ShopItem))}
    assert retirado not in refs and refs[rebajado].price_cents == 1995
    assert len(refs) == 5  # los 2 que se enseñaron (ya caducados) siguen para no repetirse; el resto se renueva
    assert sorted(i.status for i in refs.values()) == ["caducado", "caducado", "candidato", "candidato", "nuevo"]


def test_ver_mas_trae_la_siguiente_tanda_sin_volver_a_consultar_el_catalogo(client, tienda, monkeypatch):
    connector = tienda(
        camisas=[product(f"c{i}", "camisa", "blanco") for i in range(5)],
        sudaderas=[product(f"z{i}", "zapatillas", "blanco", section="sudaderas") for i in range(4)],
    )
    _refresh(limit=2)
    assert sorted(i.category for i in _items("nuevo")) == ["calzado", "parte_superior"]
    nxt = client.get("/api/shop/next").json()
    assert (nxt["remaining"], nxt["more"]) == (2, 7)
    calzado = client.get("/api/shop/next", params={"category": "calzado"}).json()
    assert (calzado["remaining"], calzado["more"], calzado["item"]["category"]) == (1, 3, "calzado")
    assert client.get("/api/shop/next", params={"category": "capa_exterior"}).json()["item"] is None
    assert client.get("/api/shop/next", params={"category": "sombreros"}).status_code == 422
    assert client.get("/api/shop/next", params={"store": "otra"}).status_code == 404

    # Con el filtro «Calzado», «Ver más» trae más calzado: en segundo plano y sin pedir el catálogo.
    connector.calls.clear()
    monkeypatch.setattr(shopping, "LOW_FIT", 0.0)
    assert client.post("/api/shop/more", json={"category": "calzado"}).status_code == 202
    shopping.wait_idle()
    assert connector.asked("lista") == [] and len(connector.asked("detalle")) == 3
    state = client.get("/api/shop/state").json()
    assert state["running"] is False and state["pending"] == 5
    assert state["last_more"] == {"added": 3, "low": False, "error": None}
    calzado = client.get("/api/shop/next", params={"category": "calzado"}).json()
    assert (calzado["remaining"], calzado["more"]) == (4, 0)
    nuevas = [i for i in _items("nuevo") if i.category == "calzado"]
    assert len(nuevas) == 4 and all(len(i.photos) == 2 and i.sizes and i.reasons for i in nuevas)

    # Sin filtro, lo que quede, de N en N. Cuando la nota media baja del umbral, se avisa.
    monkeypatch.setattr(shopping, "LOW_FIT", 99.0)
    result = _more(limit=3)
    assert (result["added"], result["low"]) == (3, True) and result["mean"] < 99
    assert client.get("/api/shop/state").json()["last_more"]["low"] is True
    assert client.get("/api/shop/next").json()["more"] == 1
    assert _more(limit=3)["added"] == 1

    # Ya no quedan candidatos: no se pide nada y se dice.
    connector.calls.clear()
    result = _more()
    assert (result["added"], result["low"], result["mean"]) == (0, False, None) and connector.calls == []
    assert client.get("/api/shop/next").json()["more"] == 0
    assert client.get("/api/shop/state").json()["last_more"] == {"added": 0, "low": False, "error": None}
    # La siguiente consulta semanal empieza de cero.
    _refresh(today=INVIERNO + timedelta(days=7))
    assert client.get("/api/shop/state").json()["last_more"] is None


def test_ver_mas_puntua_con_los_gustos_de_ahora_y_salta_lo_que_no_sirve(client, tienda):
    connector = tienda(camisas=[
        product("a", "camisa", "negro"), product("b", "camisa", "negro"), product("c1", "camisa", "beige"),
        product("c2", "camisa", "beige"), product("agotado", "camisa", "negro"),
    ])
    connector.details["agotado"] = ShopDetail(
        price_cents=1000, sizes=[{"name": "M", "in_stock": False}], photo_urls=["https://fotos.test/x-e1.jpg"]
    )
    _refresh(limit=2)
    negra, beige = _items("nuevo")
    assert (negra.product_ref, beige.product_ref) == ("zara:a", "zara:c1")  # variada: no dos negras

    # Sin valoraciones, la siguiente sería otra negra (empatan y va por orden). Pero el usuario descarta la
    # negra por el color y se queda la beige: «Ver más» puntúa con eso y trae antes la beige.
    client.post(f"/api/shop/items/{negra.id}/dislike")
    assert client.post(f"/api/shop/items/{negra.id}/reason", json={"reason": "color"}).status_code == 204
    client.post(f"/api/shop/items/{beige.id}/like")
    connector.calls.clear()
    assert _more(limit=1)["added"] == 1
    assert [i.product_ref for i in _items("nuevo")] == ["zara:c2"] and connector.asked("detalle") == ["c2"]
    assert "Te suele gustar el beige" not in _texts(_items("nuevo")[0].reasons)  # un solo voto aún no es motivo

    # El agotado se pide una vez, no sirve, entra el siguiente y no se vuelve a intentar hasta la consulta semanal.
    assert _more(limit=1)["added"] == 1 and connector.asked("detalle")[1:] == ["agotado", "b"]
    assert _more(limit=2)["added"] == 0 and connector.asked("detalle").count("agotado") == 1
    assert client.get("/api/shop/next").json()["more"] == 0

    # Un fallo de red no dice nada del producto: se apunta y se podrá reintentar.
    connector.products["camisas"].append(product("lento", "camisa", "gris"))
    _refresh(today=INVIERNO + timedelta(days=7), limit=0)
    connector.detail = lambda store_data: (_ for _ in ()).throw(ShopError("tiempo agotado (20 s)"))
    result = _more(today=INVIERNO + timedelta(days=7), limit=1)
    assert result["added"] == 0 and result["failed"] == 2
    assert result["error"].endswith("tiempo agotado (20 s)")
    assert client.get("/api/shop/state").json()["last_more"]["error"] == result["error"]
    assert client.get("/api/shop/next").json()["more"] == 2


def test_el_cupo_se_reparte_entre_tiendas_y_la_lista_es_una_sola(client, tienda):
    grande = tienda(camisas=[product(f"g{i}", "camisa", "negro") for i in range(12)])
    pequena = tienda(key="otra", name="Otra", camisas=[
        product(f"p{i}", "camisa", "rosa", store="otra", name=f"Camisa cropped p{i}") for i in range(3)
    ])
    # La tanda semanal: el cupo (4) a medias, aunque las de la tienda pequeña tengan peor nota.
    _refresh(limit=4)
    assert sorted(i.store for i in _items("nuevo")) == ["otra", "otra", "zara", "zara"]
    assert len(grande.asked("detalle")) == 2 and len(pequena.asked("detalle")) == 2

    # Al enseñarlas, una sola lista por nota, venga de la tienda que venga.
    orden = []
    while (nxt := client.get("/api/shop/next").json())["item"]:
        orden.append((nxt["item"]["store_name"], nxt["item"]["score"]))
        if len(orden) == 1:
            assert (nxt["remaining"], nxt["more"]) == (4, 11)
            otra = client.get("/api/shop/next", params={"store": "otra"}).json()
            assert (otra["item"]["store"], otra["remaining"], otra["more"]) == ("otra", 2, 1)
        client.post(f"/api/shop/items/{nxt['item']['id']}/like")
    assert [tienda_ for tienda_, _ in orden] == ["Zara", "Zara", "Otra", "Otra"]

    # «Ver más»: a la pequeña solo le queda una; el resto del cupo lo llena la grande.
    assert _more(limit=4)["added"] == 4
    assert sorted(i.store for i in _items("nuevo")) == ["otra", "zara", "zara", "zara"]
    # Y con el filtro de tienda, solo de esa.
    assert _more(limit=4, store="otra")["added"] == 0
    assert _more(limit=2, store="zara")["added"] == 2
    assert [i.store for i in _items("nuevo")].count("zara") == 5

    # Una tienda desactivada no entra ni en la lista ni en «Ver más».
    with SessionLocal() as db:
        shopping.set_store(db, "otra", False, None)
    assert all(i["store"] == "zara" for i in [client.get("/api/shop/next").json()["item"]])
    assert client.post("/api/shop/more", json={"store": "otra"}).status_code == 409


# ---------- «Volver» y el motivo del descarte


def test_volver_deshace_las_decisiones_una_a_una_y_no_cuentan_al_aprender(client, tienda):
    tienda(camisas=[product("a"), product("b"), product("c")])
    _refresh()
    first = client.get("/api/shop/next").json()
    assert first["can_undo"] is False and client.post("/api/shop/undo").status_code == 409
    a = first["item"]
    b = client.post(f"/api/shop/items/{a['id']}/like").json()["item"]
    after = client.post(f"/api/shop/items/{b['id']}/dislike").json()
    assert after["remaining"] == 1 and after["can_undo"] is True
    decided = {i.id: i for i in _items()}
    assert decided[a["id"]].decided_at and decided[b["id"]].decided_at  # se guarda cuándo se decidió
    learned = _taste()
    assert learned.types["camisa"] == pytest.approx([0.8, 1.2])  # un me gusta entero y un descarte, que cuenta poco

    # Primera vuelta: el descarte. La tarjeta vuelve tal cual, con sus fotos.
    back = client.post("/api/shop/undo").json()
    assert back["item"]["id"] == b["id"] and back["item"]["status"] == "nuevo"
    assert (back["remaining"], back["can_undo"]) == (2, True)
    assert client.get(back["item"]["photos"][0]["url"]).status_code == 200
    assert _taste().types["camisa"] == [1.0, 1.0]

    # Segunda vuelta: el me gusta, que sale de «Me gustan».
    back = client.post("/api/shop/undo").json()
    assert back["item"]["id"] == a["id"] and (back["remaining"], back["can_undo"]) == (3, False)
    assert client.get("/api/shop/liked").json() == []
    assert client.get("/api/shop/state").json()["liked"] == 0
    restored = {i.id: i for i in _items()}[a["id"]]
    assert (restored.liked_at, restored.expires_at, restored.decided_at) == (None, None, None)
    assert _taste().types == {} and _taste().colors == {}  # como si no se hubiera valorado nada
    assert client.post("/api/shop/undo").status_code == 409

    # Se puede volver a decidir lo deshecho, y ahora con otro resultado.
    assert client.post(f"/api/shop/items/{a['id']}/dislike").status_code == 200
    assert _taste().types["camisa"] == [-0.2, 0.2]


def test_volver_solo_alcanza_a_la_tanda_actual(client, tienda):
    tienda(camisas=[product("a"), product("b"), product("c")])
    _refresh()
    a, b, c = _items()
    client.post(f"/api/shop/items/{a.id}/dislike")
    client.post(f"/api/shop/items/{b.id}/like")
    client.post(f"/api/shop/items/{c.id}/like")
    assert all(storage.exists(p) for p in a.photos)  # lo descartado guarda las fotos mientras se pueda deshacer

    # Quitar de «Me gustan» no es una decisión de Descubrir: no se deshace.
    assert client.delete(f"/api/shop/items/{c.id}").status_code == 204
    assert client.post("/api/shop/undo").json()["item"]["id"] == b.id
    client.post(f"/api/shop/items/{b.id}/like")

    # La consulta semanal cierra la tanda: ya no hay vuelta atrás y lo descartado suelta sus fotos.
    _refresh(today=INVIERNO + timedelta(days=7))
    assert client.get("/api/shop/next").json()["can_undo"] is False
    assert client.post("/api/shop/undo").status_code == 409
    assert not any(storage.exists(p) for p in a.photos)
    by_id = {i.id: i for i in _items()}
    assert (by_id[a.id].status, by_id[a.id].photos) == ("descartado", [])
    assert by_id[b.id].status == "gustado" and all(storage.exists(p) for p in by_id[b.id].photos)
    assert by_id[a.id].decided_at  # la fecha de la decisión se conserva


def test_el_motivo_del_descarte_se_guarda_y_cambia_lo_aprendido(client, tienda):
    tienda(camisas=[
        product("a", "camisa", "rosa", price=1995, name="Camisa cropped"), product("b", "camisa", "negro"),
        product("c", "camisa", "gris"),
    ])
    _refresh()
    a, b, c = _items()
    client.post(f"/api/shop/items/{a.id}/dislike")
    assert _taste().colors["rosa"] == [-0.2, 0.2]  # sin motivo: repartido y muy flojo

    assert client.post(f"/api/shop/items/{a.id}/reason", json={"reason": "caro"}).status_code == 204
    learned = _taste()
    assert learned.prices == {"hasta_25": [-1.0, 1.0]} and not (learned.colors or learned.types or learned.words)
    assert client.post(f"/api/shop/items/{a.id}/reason", json={"reason": "estilo"}).status_code == 204  # se puede cambiar
    learned = _taste()
    assert learned.words == {"cropped": [-1.0, 1.0]} and learned.types == {"camisa": [-0.5, 0.5]}
    assert not (learned.colors or learned.prices)
    assert _items()[0].discard_reason == "estilo"
    # Lo que queda por ver se vuelve a puntuar con lo aprendido.
    assert any("Sueles descartar" in m["text"] for i in _items("nuevo") for m in i.reasons) is False  # un voto no basta
    assert client.post(f"/api/shop/items/{a.id}/reason", json={"reason": "ya_tengo"}).status_code == 204
    assert _taste().types == {} and _taste().words == {}

    # Solo vale para lo descartado, y solo los motivos conocidos.
    assert client.post(f"/api/shop/items/{b.id}/reason", json={"reason": "color"}).status_code == 409
    assert client.post(f"/api/shop/items/{a.id}/reason", json={"reason": "feo"}).status_code == 422
    assert client.post("/api/shop/items/999/reason", json={"reason": "color"}).status_code == 404
    client.post(f"/api/shop/items/{c.id}/like")
    client.delete(f"/api/shop/items/{c.id}")  # gustó y luego se quitó: sigue contando como me gusta
    assert client.post(f"/api/shop/items/{c.id}/reason", json={"reason": "color"}).status_code == 409
    # Al deshacer el descarte, el motivo se va con él.
    client.post(f"/api/shop/items/{a.id}/reason", json={"reason": "color"})
    assert client.post("/api/shop/undo").json()["item"]["id"] == a.id
    assert _items()[0].discard_reason is None and "rosa" not in _taste().colors


# ---------- La temporada, leyendo la descripción


def test_la_descripcion_delata_la_ropa_de_verano_y_entra_el_siguiente_candidato(client, tienda):
    connector = tienda(sudaderas=[
        product("corta", "jersey", "negro", section="sudaderas", season="invierno", name="Jersey punto calado"),
        product("larga", "jersey", "gris", section="sudaderas", season="invierno", name="Jersey punto"),
    ])
    sizes = [{"name": "M", "in_stock": True}]
    connector.details["corta"] = ShopDetail(
        price_cents=None, sizes=sizes, photo_urls=["https://fotos.test/corta-e1.jpg"],
        description="Jersey de punto.   Cuello redondo y manga corta. " + "Acabados en rib. " * 60,
    )
    connector.details["larga"] = ShopDetail(
        price_cents=None, sizes=sizes, photo_urls=["https://fotos.test/larga-e1.jpg"],
        description="Jersey de punto con cuello redondo y manga larga.",
    )
    with SessionLocal() as db:  # sin el corte raro del nombre, la de manga corta iría primero (negro)
        shopping.refresh(db, today=INVIERNO, limit=0)
    assert not any(shopping.out_of_season(c, INVIERNO) for c in _items("candidato"))  # por el nombre, nada que objetar

    with SessionLocal() as db:
        ranked = shopping._ranked(shopping.Context.load(db), shopping.candidates_left(db, INVIERNO), 2)
        corta = next(row for _v, _r, row in ranked if row.product_ref == "zara:corta")
        scores = shopping._promote(db, shopping.Context.load(db), [(0, [], corta)] + ranked, 1, INVIERNO, lambda *a: None)
    assert len(scores) == 1
    assert connector.asked("detalle") == ["corta", "larga"]  # se leyó su ficha, no valía y entró la siguiente
    assert connector.asked("foto") == ["https://fotos.test/larga-e1.jpg"]  # de la descartada no se bajan fotos
    assert [i.product_ref for i in _items("nuevo")] == ["zara:larga"]
    assert "manga larga" in _items("nuevo")[0].details

    saved = _items("candidato")[0]
    assert saved.season == "verano" and "manga corta" in saved.details
    assert saved.details.startswith("Jersey de punto. Cuello redondo")  # el nombre no viene en `details` del falso
    assert len(saved.details) <= shopping.DESCRIPTION_MAX + 1  # recortada
    assert client.get("/api/shop/next").json()["more"] == 0  # hasta mayo no es candidata

    # La semana siguiente no se vuelve a gastar una petición en ella: ya se sabe que es de verano.
    connector.calls.clear()
    _refresh(today=INVIERNO + timedelta(days=7))
    assert "corta" not in connector.asked("detalle") and [i.status for i in _items()] == ["caducado"]
    # En verano sí se propone.
    _refresh(today=date(2027, 7, 2))
    assert "zara:corta" in [i.product_ref for i in _items("nuevo")]


def test_el_detalle_de_zara_trae_la_descripcion_y_el_tejido_principal():
    store_data = {"keyword": "x", "seo_id": "05854122", "discern_id": 590649460, "color_id": "800"}
    data = _fixture("zara_detalle.json")
    data["product"]["detail"]["detailedComposition"] = {"parts": [
        {"description": "EXTERIOR", "components": [{"material": "Lino", "percentage": "70%"},
                                                   {"material": "algodón", "percentage": "30%"}]},
        {"description": "FORRO", "components": [{"material": "poliéster", "percentage": "100%"}]},
    ]}
    description = zara.parse_detail(data, store_data).description
    assert description.startswith("Sobrecamisa regular fit")
    assert description.endswith("Tejido principal: lino, poliéster.") and "algodón" not in description
    assert shopping.summer_text(description)

    # Si el color no trae descripción, vale la de la ficha (seo); sin composición no se inventa nada.
    del data["product"]["detail"]["detailedComposition"]
    data["product"]["detail"]["colors"][0]["description"] = ""
    assert zara.parse_detail(data, store_data).description == data["product"]["seo"]["description"].strip()


def test_las_columnas_nuevas_se_anaden_a_una_tabla_shop_items_que_ya_existia():
    from sqlalchemy import create_engine

    from app import db as database

    old = create_engine("sqlite://")
    with old.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE shop_items (id INTEGER PRIMARY KEY, status VARCHAR(20))")
        conn.exec_driver_sql("INSERT INTO shop_items (status) VALUES ('descartado')")
    original, database.engine = database.engine, old
    try:
        database._add_missing_columns()
    finally:
        database.engine = original
    with old.begin() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(shop_items)")}
        row = conn.exec_driver_sql("SELECT decided_at, can_undo, discard_reason FROM shop_items").one()
    assert {"decided_at", "can_undo", "discard_reason"} <= columns and tuple(row) == (None, None, None)


def test_cada_senal_pesa_lo_suyo_al_aprender(client):
    """Comprar manda (3), un me gusta cuenta 1, uno que no acabó en compra 0,5 y un descarte casi nada."""
    from datetime import datetime, timezone

    from app.db import SessionLocal
    from app.models import ShopItem

    def add(db, ref, status, liked=False):
        db.add(ShopItem(
            store="zara", product_ref=ref, name="Prenda", price_cents=2995, url="https://example.com",
            type="camisa", category="parte_superior", color="negro", pattern="liso", style="casual",
            season="todo_el_ano", status=status, liked_at=datetime.now(timezone.utc) if liked else None,
            batch=datetime.now(timezone.utc).date(),
        ))

    with SessionLocal() as db:
        add(db, "comprada", shopping.BOUGHT, liked=True)
        db.commit()
        assert shopping.load_shop_taste(db).types["camisa"] == [3.0, 3.0]
        add(db, "gustada", shopping.LIKED, liked=True)
        add(db, "caducada", shopping.EXPIRED, liked=True)
        add(db, "quitada", shopping.DISCARDED, liked=True)
        add(db, "sin_valorar", shopping.EXPIRED)
        add(db, "descartada", shopping.DISCARDED)
        db.commit()
        net, total = shopping.load_shop_taste(db).types["camisa"]
    assert (net, total) == pytest.approx((3 + 1 + 0.5 + 0.5 - 0.2, 3 + 1 + 0.5 + 0.5 + 0.2))


# ---------- El buscador por referencia


@pytest.mark.parametrize(
    ("texto", "seo_id", "color", "v1"),
    [
        ("3918/300", "03918300", None, None),
        ("3918/300/800", "03918300", "800", None),
        ("03918300", "03918300", None, None),
        ("3918300", "03918300", None, None),
        ("0391 8300 800", "03918300", "800", None),  # como viene en la etiqueta
        ("REF. 3918/300", "03918300", None, None),
        ("  ref: 3918-300  ", "03918300", None, None),
        ("Referencia Nº 3918.300", "03918300", None, None),
        ("https://www.zara.com/es/es/cazadora-tecnica-combinado-polar-p03918300.html?v1=565710389&v2=2432", "03918300",
         None, "565710389"),
        ("https://www.zara.com/es/es/cazadora-tecnica-combinado-polar-p03918300.html", "03918300", None, None),
        ("www.zara.com/es/en/-p03918300.html?v1=1", "03918300", None, "1"),
        ("zara.com/es/es/share/-p03918300.html?v1=565710389&utm_campaign=productShare", "03918300", None, "565710389"),
        ("Mira esta cazadora en Zara: https://www.zara.com/es/es/share/cazadora-p03918300.html?v1=565710389.",
         "03918300", None, "565710389"),
        ("https://m.zara.com/fr/fr/veste-p03918300.html?v1=abc", "03918300", None, None),
    ],
)
def test_el_buscador_entiende_las_referencias_y_los_enlaces_de_zara(texto, seo_id, color, v1):
    query = zara.parse_query(texto)
    assert (query.seo_id, query.color_id, query.v1, query.text) == (seo_id, color, v1, None)


def test_el_buscador_distingue_el_texto_libre_la_basura_y_los_enlaces_de_otras_tiendas():
    assert zara.parse_query("  cazadora   lana negra ") == zara.ZaraQuery(text="cazadora lana negra")
    assert zara.parse_query("pantalón negro 100% algodón").text == "pantalón negro 100% algodón"
    for basura in ("", "   ", "ref", "12", "3918", "3918/30", "3918/300/80", "123456789012", "#!?", "3918+300", "ab"):
        with pytest.raises(SearchError) as error:
            zara.parse_query(basura)
        assert not isinstance(error.value, NotThisStore), basura
    with pytest.raises(SearchError, match="7 cifras, tipo 3918/300"):
        zara.parse_query("3918/30")
    # Un enlace de Zara sin la referencia (la portada, una categoría, un enlace corto) no sirve…
    for sin_ref in ("https://www.zara.com/es/", "https://www.zara.com/es/es/hombre-camisas-l737.html", "https://go.zara.com/x7Yz"):
        with pytest.raises(SearchError, match="no lleva la referencia"):
            zara.parse_query(sin_ref)
    # … y el de otra tienda, tampoco: se dice que todavía no se sabe buscar ahí.
    for otra in ("https://www.pullandbear.com/es/cazadora-l03918300.html", "https://vm.tiktok.com/ZNd123/",
                 "bershka.com/es/sudadera-c0p101.html", "https://zara.com.tienda-falsa.es/-p03918300.html",
                 "https://notzara.com/es/-p03918300.html"):
        with pytest.raises(NotThisStore, match="Todavía no sé buscar en esa tienda"):
            zara.parse_query(otra)


def test_la_respuesta_del_buscador_de_zara_da_un_producto_por_color():
    products = zara.parse_search(_fixture("zara_busqueda.json"), 12)

    # Fuera el repetido y los calcetines; cada color de una misma referencia es un resultado.
    assert [(p.name, p.store_color, p.product_ref) for p in products] == [
        ("Cazadora técnica combinado polar", "Negro", "zara:03918300-800"),
        ("Cazadora técnica combinado polar", "Khaki", "zara:03918300-505"),
        ("Cazadora regular fit con lana", "Negro", "zara:08281765-800"),
        ("Cazadora regular fit con lana", "Negro / Marrón", "zara:04517500-099"),
        ("Cazadora cropped fit 100% lana", "Negro", "zara:08491305-800"),
    ]
    first = products[0]
    assert (first.type, first.category, first.color, first.price_cents) == ("chaqueta", "capa_exterior", "negro", 3995)
    assert first.url == "https://www.zara.com/fr/fr/cazadora-tecnica-combinado-polar-p03918300.html?v1=565710389"
    assert first.store_data == {
        "keyword": "cazadora-tecnica-combinado-polar", "seo_id": "03918300", "discern_id": 565710389, "color_id": "800",
    }
    assert first.section == "" and products[1].color == "verde oliva"
    assert len(zara.parse_search(_fixture("zara_busqueda.json"), 2)) == 2
    assert zara.parse_search({}, 12) == [] and zara.parse_search({"results": [{}, {"content": None}]}, 12) == []


def test_la_ficha_de_una_referencia_da_un_resultado_por_color():
    data = _fixture("zara_producto.json")
    todos = zara.parse_product_page(data, zara.ZaraQuery(seo_id="03918300"), 12)
    assert [(p.store_color, p.product_ref, p.store_data["discern_id"]) for p in todos] == [
        ("Khaki", "zara:03918300-505", 548232269), ("Negro", "zara:03918300-800", 548232268),
    ]
    assert todos[0].name == "Cazadora técnica combinado polar" and todos[0].price_cents == 3995
    assert todos[1].url.endswith("/cazadora-tecnica-combinado-polar-p03918300.html?v1=548232268")
    # Con el color en la referencia, solo ese; con el del enlace, ese va primero; si no existe, todos.
    solo = zara.parse_product_page(data, zara.ZaraQuery(seo_id="03918300", color_id="800"), 12)
    assert [p.store_color for p in solo] == ["Negro"]
    primero = zara.parse_product_page(data, zara.ZaraQuery(seo_id="03918300", v1="548232268"), 12)
    assert [p.store_color for p in primero] == ["Negro", "Khaki"]
    assert len(zara.parse_product_page(data, zara.ZaraQuery(seo_id="03918300", color_id="999"), 12)) == 2
    assert len(zara.parse_product_page(data, zara.ZaraQuery(seo_id="03918300"), 1)) == 1
    # Cada resultado encuentra luego sus fotos y sus tallas en esa misma ficha.
    detail = zara.parse_detail(data, solo[0].store_data)
    assert [url.rsplit("/", 1)[1] for url in detail.photo_urls] == ["03918309800-e1.jpg?w=1280", "03918309800-e2.jpg?w=1280"]
    assert detail.sizes[0] == {"name": "S", "in_stock": True} and detail.color_hex == "#242524"

    # Si el nombre no dice qué es, lo dice la familia de Zara; y lo que no cabe en el armario no sale.
    data["product"]["name"] = "RELAXED FIT COMBINADO POLAR"
    assert zara.parse_product_page(data, zara.ZaraQuery(seo_id="03918300"), 12)[0].type == "chaqueta"
    data["product"].update(name="VESTIDO MIDI SATINADO", familyName="VESTIDO", subfamilyName="")
    assert zara.parse_product_page(data, zara.ZaraQuery(seo_id="03918300"), 12) == []


def test_zara_busca_una_referencia_en_su_ficha_y_el_texto_en_el_buscador(monkeypatch):
    import httpx

    connector = zara.ZaraConnector(pause=0)
    buena = zara.BASE + "/cazadora-tecnica-combinado-polar-p03918300.html?ajax=true"
    vestido = _fixture("zara_producto.json")
    vestido["product"].update(name="VESTIDO MIDI SATINADO", familyName="VESTIDO", subfamilyName="")
    answers = {
        zara.BASE + "/-p03918300.html?ajax=true": httpx.Response(278, json={"location": buena, "body": {}}),
        buena: httpx.Response(200, json=_fixture("zara_producto.json")),
        # Una referencia que no existe manda a la portada.
        zara.BASE + "/-p09999999.html?ajax=true": httpx.Response(278, json={"location": "https://www.zara.com/es/?ajax=true"}),
        zara.BASE + "/-p01111111.html?ajax=true": httpx.Response(404, json={}),
        zara.BASE + "/-p02222222.html?ajax=true": httpx.Response(403, text="Access Denied"),
        zara.BASE + "/-p03333333.html?ajax=true": httpx.Response(200, json=vestido),
    }
    asked = []

    def fake_get(self, url, pause, headers=None):
        asked.append(url)
        if url.startswith(zara.SEARCH):
            return httpx.Response(200, json=_fixture("zara_busqueda.json") if "cazadora" in url else {"results": []})
        return answers[url]

    monkeypatch.setattr(zara.ZaraConnector, "_get", fake_get)

    found = connector.search("3918/300/800", 12)
    assert [p.product_ref for p in found] == ["zara:03918300-800"] and asked == [zara.BASE + "/-p03918300.html?ajax=true", buena]
    # La ficha ya trae las fotos y las tallas: pedir el detalle de sus colores no gasta otra petición.
    assert connector.detail(found[0].store_data).photo_urls and len(asked) == 2
    assert len(connector.search("https://www.zara.com/es/es/x-p03918300.html?v1=548232268", 12)) == 2

    for texto in ("9999999", "1111111"):
        with pytest.raises(SearchError, match="No he encontrado nada con esa referencia"):
            connector.search(texto, 12)
    with pytest.raises(SearchError, match="«Vestido midi satinado» no es un tipo de prenda que quepa en el armario"):
        connector.search("3333333", 12)
    with pytest.raises(ShopError, match="HTTP 403") as error:
        connector.search("2222222", 12)
    assert not isinstance(error.value, SearchError)  # eso sí es un fallo de la tienda

    # El texto libre va al buscador de la web, solo en hombre y con pocos resultados.
    asked.clear()
    found = connector.search("cazadora lana negra", 12)
    assert len(found) == 5 and len(connector.search("cazadora lana negra", 3)) == 3
    assert "query=cazadora%20lana%20negra" in asked[0] and "section=MAN" in asked[0]
    with pytest.raises(SearchError, match="No he encontrado nada en Zara con «xyzzy»"):
        connector.search("xyzzy", 12)


def _lookup(query: str) -> list[ShopItem]:
    with SessionLocal() as db:
        return shopping.lookup(db, query)


def _status(ref: str) -> str | None:
    with SessionLocal() as db:
        return db.scalar(select(ShopItem.status).where(ShopItem.product_ref == ref))


def test_el_buscador_guarda_lo_que_encuentra_como_buscado_y_no_es_una_propuesta(client, tienda, photo_bytes):
    _garment(client, photo_bytes, name="Vaquero azul", type="vaquero", color_primary={"name": "azul", "hex": "#2f5fa8"})
    connector = tienda(camisas=[product("a")])
    with SessionLocal() as db:
        shopping.set_store(db, "zara", False, None)  # se busca también con la tienda desactivada
    connector.found["3918/300"] = [product("negra", "chaqueta", "negro", price=3995), product("caqui", "chaqueta", "verde oliva")]

    found = client.post("/api/shop/lookup", json={"query": "  3918/300 "})
    assert found.status_code == 200 and connector.asked("busca") == ["3918/300"]
    negra, caqui = found.json()
    assert (negra["name"], negra["status"], negra["saved"], negra["garment_id"]) == ("Chaqueta negra", "buscado", None, None)
    assert negra["price_cents"] == 3995 and negra["store_name"] == "Zara" and negra["reasons"]
    assert negra["sizes"] == [{"name": "M", "in_stock": True}, {"name": "L", "in_stock": False}]
    assert len(negra["photos"]) == 2 and client.get(negra["photos"][0]["url"]).status_code == 200
    assert set(_items("buscado")[0].photos) <= referenced_photos()  # la limpieza de huérfanas no las toca
    assert "Manga larga." in _items("buscado")[0].details

    # No es una propuesta: ni en Descubrir, ni en los contadores, ni entre los candidatos, ni al aprender.
    with SessionLocal() as db:
        shopping.set_store(db, "zara", True, None)
    assert client.get("/api/shop/next").json() == {
        "item": None, "remaining": 0, "more": 0, "can_undo": False, "refilling": False, "queue": [],
    }
    state = client.get("/api/shop/state").json()
    assert (state["pending"], state["liked"]) == (0, 0) and client.get("/api/shop/liked").json() == []
    assert _taste() == shopping.ShopTaste()
    assert client.post(f"/api/shop/items/{negra['id']}/dislike").status_code == 409  # eso es cosa de Descubrir
    assert client.post("/api/shop/undo").status_code == 409

    # Buscar lo mismo otra vez no duplica nada ni vuelve a bajar las fotos.
    connector.calls.clear()
    again = client.post("/api/shop/lookup", json={"query": "3918/300"}).json()
    assert [i["id"] for i in again] == [negra["id"], caqui["id"]]
    assert connector.asked("detalle") == [] and connector.asked("foto") == [] and len(_items("buscado")) == 2


def test_el_buscador_dice_en_claro_por_que_no_hay_nada(client, tienda):
    connector = tienda()
    connector.found["otra-tienda"] = NotThisStore("Todavía no sé buscar en esa tienda")
    connector.found["caida"] = ShopError("HTTP 403")
    connector.found["rota"] = KeyError("un fallo de programación")
    connector.found["sin-foto"] = [product("sin-foto")]
    connector.found["lenta"] = [product("lenta")]
    connector.details["sin-foto"] = ShopDetail(price_cents=1000, sizes=[], photo_urls=[])

    def falla(query, codigo):
        response = client.post("/api/shop/lookup", json={"query": query})
        assert response.status_code == codigo, response.text
        return response.json()["detail"]

    assert falla("9999/999", 404) == "No he encontrado nada con esa referencia"
    assert falla("otra-tienda", 404) == "Todavía no sé buscar en esa tienda"
    assert falla("   ", 404) == "Escribe una referencia, un enlace o qué prenda buscas"
    assert falla("caida", 503) == "Zara no responde ahora (HTTP 403)"
    assert falla("rota", 503) == "No se pudo buscar en Zara: error inesperado"
    assert "no tiene fotos de producto" in falla("sin-foto", 404)
    connector.detail = lambda store_data: (_ for _ in ()).throw(ShopError("tiempo agotado (20 s)"))
    assert falla("lenta", 503) == "Zara no responde ahora (tiempo agotado (20 s))"
    assert client.post("/api/shop/lookup", json={"query": "x" * 601}).status_code == 422
    assert _items() == []  # nada de eso deja rastro

    # Una consulta del catálogo en marcha (o un «Ver más») no frena el buscador; otra búsqueda, sí.
    assert shopping._lock.acquire(blocking=False)
    try:
        assert falla("9999/999", 404) == "No he encontrado nada con esa referencia"
    finally:
        shopping._lock.release()
    assert shopping._lookup_lock.acquire(blocking=False)
    try:
        assert "buscando otra cosa" in falla("9999/999", 409)
    finally:
        shopping._lookup_lock.release()


def test_el_buscador_reutiliza_lo_que_ya_existia_sea_cual_sea_su_estado(client, tienda, analyzers):
    connector = tienda(camisas=[product(ref) for ref in ("pendiente", "gustada", "descartada", "comprada", "zcandidata")])
    _refresh(limit=4)
    by_ref = {i.product_ref: i for i in _items()}
    assert len(by_ref) == 4 and _status("zara:zcandidata") == "candidato"
    analyzers(FakeAnalyzer("codex", json.dumps(VALID_DRAFT)), FakeAnalyzer("claude"))
    client.post(f"/api/shop/items/{by_ref['zara:gustada'].id}/like")
    client.post(f"/api/shop/items/{by_ref['zara:descartada'].id}/dislike")
    client.post(f"/api/shop/items/{by_ref['zara:descartada'].id}/reason", json={"reason": "color"})
    garment_id = client.post(f"/api/shop/items/{by_ref['zara:comprada'].id}/bought", json={"size": "M"}).json()["garment_id"]
    _refresh(today=INVIERNO + timedelta(days=7), limit=0)  # se cierra la tanda: lo descartado suelta sus fotos
    assert _status("zara:pendiente") == "caducado" and _items("descartado")[0].photos == []
    antes = _taste()
    assert antes.colors["blanco"] == pytest.approx([3 + 1 - 1, 3 + 1 + 1])  # comprada, gustada y descartada por el color

    connector.found["todo"] = [product(ref) for ref in ("pendiente", "gustada", "descartada", "comprada", "zcandidata", "nueva")]
    connector.calls.clear()
    found = {i["name"].split()[-1]: i for i in client.post("/api/shop/lookup", json={"query": "todo"}).json()}
    with SessionLocal() as db:
        assert len(list(db.scalars(select(ShopItem)))) == 6  # ninguna fila repetida
    assert {ref: (i["status"], i["saved"]) for ref, i in found.items()} == {
        "pendiente": ("buscado", None), "gustada": ("gustado", "gustado"), "descartada": ("buscado", None),
        "comprada": ("comprado", "comprado"), "zcandidata": ("buscado", None), "nueva": ("buscado", None),
    }
    assert all(i["id"] == by_ref[f"zara:{ref}"].id for ref, i in found.items() if f"zara:{ref}" in by_ref)
    # De lo que ya está guardado o en el armario no se vuelve a pedir nada a la tienda.
    assert sorted(connector.asked("detalle")) == ["descartada", "nueva", "pendiente", "zcandidata"]
    assert found["comprada"]["garment_id"] == garment_id and found["gustada"]["garment_id"] is None
    assert found["comprada"]["photos"][0]["id"] == client.get(f"/api/garments/{garment_id}").json()["photo_front"]["id"]
    assert all(len(i["photos"]) == 2 for i in found.values())
    # Volver a buscar algo no cambia lo que ya se dijo de ello.
    assert _taste() == antes and client.get("/api/shop/state").json()["liked"] == 1

    # Lo descartado se puede volver a guardar: pasa a Me gustan y deja de contar como descarte.
    assert client.post(f"/api/shop/items/{found['descartada']['id']}/like").status_code == 200
    guardada = next(i for i in _items("gustado") if i.product_ref == "zara:descartada")
    assert (guardada.prev_status, guardada.discard_reason, guardada.can_undo) == (None, None, False)
    assert guardada.expires_at and _taste().colors["blanco"] == pytest.approx([3 + 1 + 1, 3 + 1 + 1])
    assert client.post("/api/shop/undo").status_code == 409  # «Volver» no deshace lo del buscador

    # Si la prenda comprada ya no está en el armario, se puede volver a meter.
    client.delete(f"/api/garments/{garment_id}")
    otra_vez = {i["name"].split()[-1]: i for i in client.post("/api/shop/lookup", json={"query": "todo"}).json()}
    assert (otra_vez["comprada"]["status"], otra_vez["comprada"]["saved"]) == ("buscado", None)
    nueva = client.post(f"/api/shop/items/{otra_vez['comprada']['id']}/bought", json={"size": "L"})  # la L no queda: da igual
    assert nueva.status_code == 200 and client.get(f"/api/garments/{nueva.json()['garment_id']}").json()["size"] == "L"


def test_me_gusta_y_ya_la_tengo_sobre_un_resultado_del_buscador(client, tienda, analyzers):
    connector = tienda()
    connector.found["3918/300"] = [
        product("gusta", "sobrecamisa", "negro", name="Sobrecamisa pana"),
        product("tengo", "jersey", "gris", name="Jersey trenzado"),
        product("agotada", "camisa", "blanco"),
    ]
    connector.details["agotada"] = ShopDetail(
        price_cents=2995, sizes=[{"name": "M", "in_stock": False}], photo_urls=["https://fotos.test/x-e1.jpg"]
    )
    gusta, tengo, agotada = client.post("/api/shop/lookup", json={"query": "3918/300"}).json()
    assert agotada["sizes"] == [{"name": "M", "in_stock": False}]  # aunque no quede ninguna talla, se enseña
    codex, _ = analyzers(FakeAnalyzer("codex", json.dumps(VALID_DRAFT)), FakeAnalyzer("claude"))

    # Me gusta: a Me gustan con su caducidad, y cuenta como cualquier otro me gusta.
    assert client.post(f"/api/shop/items/{gusta['id']}/like").status_code == 200
    liked = client.get("/api/shop/liked").json()
    assert [(i["id"], i["status"]) for i in liked] == [(gusta["id"], "gustado")] and liked[0]["expires_at"]
    assert client.get("/api/shop/state").json()["liked"] == 1
    assert _taste().types == {"sobrecamisa": [1.0, 1.0]} and _taste().words == {"pana": [1.0, 1.0]}
    assert client.post(f"/api/shop/items/{gusta['id']}/like").status_code == 200  # doble toque
    again = client.post("/api/shop/lookup", json={"query": "3918/300"}).json()
    assert [(i["status"], i["saved"]) for i in again] == [("gustado", "gustado"), ("buscado", None), ("buscado", None)]

    # Ya la tengo: al armario con las fotos de la tienda, analizada, y cuenta como una compra.
    assert client.post(f"/api/shop/items/{tengo['id']}/bought", json={"size": "XS"}).status_code == 409  # no existe
    bought = client.post(f"/api/shop/items/{tengo['id']}/bought", json={"size": "L"})  # agotada en la tienda: vale
    assert bought.status_code == 200 and bought.json()["analyzed"] is True and codex.calls == 1
    garment = client.get(f"/api/garments/{bought.json()['garment_id']}").json()
    assert (garment["brand"], garment["size"], garment["name"]) == ("Zara", "L", "Bomber negra")
    assert garment["photo_front"]["id"] == tengo["photos"][0]["id"]
    assert _status("zara:tengo") == "comprado" and _taste().types["jersey"] == [3.0, 3.0]
    # Sin talla también vale, y desde Me gustan sigue pudiéndose comprar.
    assert client.post(f"/api/shop/items/{agotada['id']}/bought", json={"size": None}).status_code == 200
    assert client.post(f"/api/shop/items/{gusta['id']}/bought", json={"size": "M"}).status_code == 200
    assert len(client.get("/api/garments").json()) == 3 and _items("buscado") == []


def test_lo_buscado_y_no_guardado_se_limpia_solo(client, tienda):
    connector = tienda(camisas=[product("vieja"), product("zcatalogo")])
    _refresh(limit=1)
    vieja = _items("nuevo")[0]
    client.post(f"/api/shop/items/{vieja.id}/dislike")
    _refresh(today=INVIERNO + timedelta(days=7), limit=0)
    connector.found["ref"] = [product(vieja.product_ref.split(":")[1]), product("suelta"), product("guardada")]
    descartada, suelta, guardada = _lookup("ref")
    assert descartada.id == vieja.id and (descartada.status, descartada.prev_status) == ("buscado", "descartado")
    client.post(f"/api/shop/items/{guardada.id}/like")
    fotos = [*descartada.photos, *suelta.photos]
    assert len(fotos) == 4 and all(storage.exists(p) for p in fotos)

    # Antes de un día no se toca nada; pasado el día, fuera con sus fotos.
    with SessionLocal() as db:
        assert shopping.clean_lookups(db) == 0
        assert shopping.clean_lookups(db, now=now_utc() + timedelta(hours=23)) == 0
        assert shopping.clean_lookups(db, now=now_utc() + timedelta(hours=25)) == 2
    assert not any(storage.exists(p) for p in fotos)
    # Lo que era nuevo desaparece, como si no se hubiera buscado; lo descartado vuelve a estar descartado.
    assert _status("zara:suelta") is None and _status(vieja.product_ref) == "descartado"
    assert _items("descartado")[0].prev_status is None and _items("descartado")[0].photos == []
    assert _status("zara:guardada") == "gustado" and all(storage.exists(p) for p in _items("gustado")[0].photos)

    # La consulta semanal también los limpia (salvo los de hace un momento, por si hay una búsqueda
    # abierta), y lo buscado que sigue en el catálogo vuelve a ser un candidato más.
    connector.found["otra"] = [product("zcatalogo"), product("reciente")]
    catalogo, reciente = _lookup("otra")
    assert _status("zara:zcatalogo") == "buscado"  # era candidato: la misma fila
    with SessionLocal() as db:
        db.get(ShopItem, catalogo.id).first_seen_at = now_utc() - timedelta(hours=2)
        db.commit()
    _refresh(today=INVIERNO + timedelta(days=14), limit=0)
    assert _status("zara:zcatalogo") == "candidato" and _status("zara:reciente") == "buscado"
    assert not any(storage.exists(p) for p in catalogo.photos) and all(storage.exists(p) for p in reciente.photos)
    assert client.get("/api/shop/next").json()["more"] == 1  # el buscado reciente no cuenta como candidato


def test_la_columna_del_buscador_se_anade_a_una_base_de_datos_anterior():
    from sqlalchemy import create_engine

    from app import db as database

    old = create_engine("sqlite://")
    with old.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE shop_items (id INTEGER PRIMARY KEY, status VARCHAR(20), decided_at DATETIME)")
    original, database.engine = database.engine, old
    try:
        database._add_missing_columns()
    finally:
        database.engine = original
    with old.begin() as conn:
        assert "prev_status" in {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(shop_items)")}


# ---------- Los datos de la prenda, «Combina con…» y los colores


def _colores(connector: FakeConnector, *colores: tuple[str, str, str | None]) -> None:
    """Dice a la tienda falsa que esos productos son el mismo en varios colores: (ref, nombre, tono)."""
    siblings = [
        {"product_ref": f"zara:{ref}", "name": name, "hex": tone, "url": f"https://tienda.test/{ref}",
         "store_data": {"ref": ref}}
        for ref, name, tone in colores
    ]
    for ref, _name, _tone in colores:
        connector.family[ref] = siblings


def test_la_ficha_de_zara_da_la_referencia_los_colores_con_foto_y_la_composicion():
    data = _fixture("zara_producto.json")
    negro = zara.parse_product_page(data, zara.ZaraQuery(seo_id="03918300", color_id="800"), 12)[0]
    # La referencia, como en la etiqueta: modelo/calidad y, si se conoce, el color.
    assert zara.reference(negro.store_data) == "3918/300/800"
    assert zara.reference({"seo_id": "03918300"}) == "3918/300"
    assert zara.reference({"seo_id": "03918300", "color_id": "548232268"}) == "3918/300"  # eso no es un color
    assert zara.reference({}) is None and zara.ZaraConnector(pause=0).reference(negro.store_data) == "3918/300/800"

    detail = zara.parse_detail(data, negro.store_data)
    assert [(s["product_ref"], s["name"], s["hex"]) for s in detail.siblings] == [
        ("zara:03918300-505", "Khaki", "#564a31"), ("zara:03918300-800", "Negro", "#242524"),
    ]
    # Cada color lleva lo necesario para pedir su ficha: sale con sus fotos, su enlace y su referencia.
    khaki = detail.siblings[0]
    assert khaki["url"].endswith("-p03918300.html?v1=548232269") and khaki["price_cents"] == 3995
    assert "03918309505-e1" in zara.parse_detail(data, khaki["store_data"]).photo_urls[0]
    assert zara.reference(khaki["store_data"]) == "3918/300/505"
    assert detail.composition == ""  # esta ficha no la trae

    # Un color sin foto de producto (-e1) no se ofrece.
    colors = data["product"]["detail"]["colors"]
    colors[0]["xmedia"] = [m for m in colors[0]["xmedia"] if not m["name"].endswith("-e1")]
    assert [s["name"] for s in zara.parse_detail(data, negro.store_data).siblings] == ["Negro"]

    data["product"]["detail"]["detailedComposition"] = {"parts": [
        {"description": "EXTERIOR", "components": [
            {"material": "poliéster", "percentage": "55%"}, {"material": "lana", "percentage": "45%"}]},
        {"description": "FORRO", "areas": [{"components": [{"material": "poliéster", "percentage": "100%"}]}]},
    ]}
    assert zara.parse_detail(data, negro.store_data).composition == (
        "Exterior: 55% poliéster, 45% lana · Forro: 100% poliéster"
    )


def test_lo_comprado_guarda_referencia_tienda_y_enlace_y_la_referencia_se_edita_a_mano(
    client, tienda, analyzers, photo_bytes
):
    cazadora = product("a", "chaqueta", "negro")
    cazadora.store_data["reference"] = "3918/300/800"
    connector = tienda(camisas=[cazadora])
    connector.details["a"] = ShopDetail(
        price_cents=None, sizes=[{"name": "M", "in_stock": True}], photo_urls=["https://fotos.test/a-e1.jpg"],
        composition="Exterior: 55% poliéster, 45% lana",
    )
    _refresh()
    item = client.get("/api/shop/next").json()["item"]
    # Lo que enseña la ficha del visor: la referencia legible y la composición, si la tienda la da.
    assert (item["reference"], item["composition"]) == ("3918/300/800", "Exterior: 55% poliéster, 45% lana")
    assert item["product_ref"] == "zara:a" and item["colors"] == []  # solo existe en un color
    analyzers(FakeAnalyzer("codex", json.dumps(VALID_DRAFT)), FakeAnalyzer("claude"))

    bought = client.post(f"/api/shop/items/{item['id']}/bought", json={"size": "M"}).json()
    garment = client.get(f"/api/garments/{bought['garment_id']}").json()
    assert (garment["reference"], garment["store_name"], garment["store_url"]) == (
        "3918/300/800", "Zara", "https://tienda.test/a",
    )
    assert not any("price" in key or "precio" in key for key in garment)  # el precio no pasa a la prenda

    # La referencia se puede corregir y borrar a mano; la tienda y el enlace no se tocan.
    edited = client.patch(f"/api/garments/{garment['id']}", json={"reference": "3918/300"}).json()
    assert (edited["reference"], edited["store_name"]) == ("3918/300", "Zara")
    assert client.patch(f"/api/garments/{garment['id']}", json={"reference": None}).json()["reference"] is None
    assert client.patch(f"/api/garments/{garment['id']}", json={"reference": "x" * 41}).status_code == 422

    # Y cualquier prenda fotografiada puede llevar la suya; sin tienda ni enlace.
    propia = _garment(client, photo_bytes, reference="  0391 8300 800 ")
    assert (propia["reference"], propia["store_name"], propia["store_url"]) == ("0391 8300 800", None, None)
    assert _garment(client, photo_bytes)["reference"] is None

    # Con una tienda que no sabe dar referencias, no hay referencia (y no pasa nada).
    connector.reference = None
    with SessionLocal() as db:
        assert shopping.store_reference(db.get(ShopItem, item["id"])) is None


def test_las_columnas_de_tienda_y_de_colores_se_anaden_a_una_base_de_datos_anterior():
    from sqlalchemy import create_engine

    from app import db as database

    old = create_engine("sqlite://")
    with old.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE garments (id INTEGER PRIMARY KEY, name VARCHAR(120))")
        conn.exec_driver_sql("CREATE TABLE shop_items (id INTEGER PRIMARY KEY, status VARCHAR(20))")
    original, database.engine = database.engine, old
    try:
        database._add_missing_columns()
    finally:
        database.engine = original
    with old.begin() as conn:
        assert {"reference", "store_name", "store_url"} <= {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(garments)")
        }
        assert {"siblings", "composition"} <= {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(shop_items)")}


def _prenda(client, photo_bytes, name, type, color, season="todo_el_ano", **extra) -> int:
    return _garment(
        client, photo_bytes, name=name, type=type, color_primary={"name": color, "hex": catalog.COLOR_HEX[color]},
        season=season, details=extra.pop("details", ""), **extra,
    )["id"]


def test_combina_con_ensena_las_mejores_prendas_de_las_otras_partes_del_cuerpo(client, tienda, photo_bytes):
    connector = tienda()
    connector.found["sudadera"] = [product(
        "s", "sudadera", "gris", name="Sudadera cremallera", details="sudadera con cremallera", season="invierno",
    )]
    item = client.post("/api/shop/lookup", json={"query": "sudadera"}).json()[0]
    url = f"/api/shop/items/{item['id']}/matches"
    assert item["status"] == "buscado"  # vale para cualquier estado, también recién buscado
    assert client.get(url).json() == {"wardrobe": 0, "groups": []}  # armario vacío: se dice

    vaqueros = [_prenda(client, photo_bytes, f"Vaquero {n}", "vaquero", "azul") for n in range(4)]
    favorito = vaqueros[3]
    client.patch(f"/api/garments/{favorito}", json={"favorite": True})
    zapatillas = _prenda(client, photo_bytes, "Zapatillas blancas", "zapatillas", "blanco")
    abrigo = _prenda(client, photo_bytes, "Abrigo negro", "abrigo", "negro", "invierno")
    cazadora = _prenda(client, photo_bytes, "Cazadora negra", "chaqueta", "negro", "invierno")
    bermuda = _prenda(client, photo_bytes, "Bermuda azul", "pantalón corto", "azul", "verano")
    chino = _prenda(client, photo_bytes, "Chino beige", "chino", "beige")  # con gris, por debajo de lo corriente
    _prenda(client, photo_bytes, "Otra sudadera", "sudadera", "negro", "invierno")  # misma parte del cuerpo

    found = client.get(url).json()
    assert found["wardrobe"] == 10
    groups = {group["category"]: group["garments"] for group in found["groups"]}
    # Solo las otras partes del cuerpo, en el orden de siempre, y como mucho tres por grupo.
    assert list(groups) == ["capa_exterior", "parte_inferior", "calzado"]
    assert [g["id"] for g in groups["calzado"]] == [zapatillas] and groups["calzado"][0]["name"] == "Zapatillas blancas"
    assert client.get(groups["calzado"][0]["photo"]["thumb_url"]).status_code == 200
    # A igual nota, primero la favorita; la cuarta se queda fuera.
    assert [g["id"] for g in groups["parte_inferior"]] == [favorito, vaqueros[0], vaqueros[1]]
    # Reglas duras: sobre una sudadera con cremallera entera no va una cazadora (un abrigo sí), y no
    # se mezcla invierno con verano.
    assert [g["id"] for g in groups["capa_exterior"]] == [abrigo]
    shown = {g["id"] for garments in groups.values() for g in garments}
    assert cazadora not in shown and bermuda not in shown and chino not in shown

    # Es la misma afinidad de Hoy y Gustos, y lo que no llega a una combinación corriente no sale.
    with SessionLocal() as db:
        row = db.get(ShopItem, item["id"])
        pair = [shopping.candidate_item(row), shopping.wardrobe_item(db.get(Garment, zapatillas))]
        assert groups["calzado"][0]["affinity"] == outfits.combo_affinity(pair) >= shopping.MATCH_MIN
        pair[1] = shopping.wardrobe_item(db.get(Garment, chino))
        assert outfits.combo_affinity(pair) < shopping.MATCH_MIN
    assert all(g["affinity"] >= shopping.MATCH_MIN for garments in groups.values() for g in garments)
    assert client.get("/api/shop/items/999/matches").status_code == 404

    # «De verano» es lo mismo que en Hoy: con un abrigo de invierno no sale una camiseta, aunque esté
    # marcada «todo el año»; una camisa sí.
    connector.found["abrigo"] = [product("ab", "abrigo", "negro", name="Abrigo lana", season="invierno")]
    coat = client.post("/api/shop/lookup", json={"query": "abrigo"}).json()[0]
    camiseta = _prenda(client, photo_bytes, "Camiseta blanca", "camiseta", "blanco")
    camisa = _prenda(client, photo_bytes, "Camisa blanca", "camisa", "blanco")
    tops = next(
        group["garments"] for group in client.get(f"/api/shop/items/{coat['id']}/matches").json()["groups"]
        if group["category"] == "parte_superior"
    )
    assert camisa in [g["id"] for g in tops] and camiseta not in [g["id"] for g in tops]
    for garment in (camiseta, camisa):
        client.delete(f"/api/garments/{garment}")

    # Si nada combina, la lista sale vacía con el armario lleno: también se dice.
    with SessionLocal() as db:
        row = db.get(ShopItem, item["id"])
        row.season = "verano"
        for garment in db.scalars(select(Garment)):
            garment.season = "invierno"
        db.commit()
    assert client.get(url).json() == {"wardrobe": 10, "groups": []}


def test_en_descubrir_se_elige_el_color_y_la_decision_es_sobre_el_que_se_ve(client, tienda):
    # La misma cazadora está en el catálogo en dos colores, y existe en un tercero que el listado no trae.
    connector = tienda(camisas=[
        product("blanca", "chaqueta", "blanco", name="Cazadora lana"),
        product("negra", "chaqueta", "negro", name="Cazadora lana"),
        product("camisa"),
    ])
    _colores(connector, ("blanca", "Blanco roto", "#f0ede4"), ("negra", "Negro", None), ("verde", "Verde", "#3f7d4f"))
    _refresh()

    # La misma prenda no sale dos veces en dos colores: de la cazadora, una sola propuesta.
    nuevos = {i.product_ref for i in _items("nuevo")}
    assert len(nuevos) == 2 and "zara:camisa" in nuevos and len(nuevos & {"zara:blanca", "zara:negra"}) == 1
    primero = (nuevos - {"zara:camisa"}).pop()
    with SessionLocal() as db:  # se enseña primero la cazadora
        db.scalars(select(ShopItem).where(ShopItem.product_ref == primero)).one().score = 99.0
        db.commit()
    item = client.get("/api/shop/next").json()["item"]
    assert item["product_ref"] == primero
    assert [(c["product_ref"], c["name"], c["hex"], c["current"]) for c in item["colors"]] == [
        ("zara:blanca", "Blanco roto", "#f0ede4", primero == "zara:blanca"),
        ("zara:negra", "Negro", catalog.COLOR_HEX["negro"], primero == "zara:negra"),  # sin tono: el de la paleta
        ("zara:verde", "Verde", "#3f7d4f", False),
    ]

    # Se elige el verde: se baja en ese momento y pasa a ser la propuesta; el otro se aparta.
    connector.calls.clear()
    verde = client.post(f"/api/shop/items/{item['id']}/color", json={"product_ref": "zara:verde"})
    assert verde.status_code == 200 and connector.asked("detalle") == ["verde"] and len(connector.asked("foto")) == 2
    verde = verde.json()
    assert (verde["status"], verde["store_color"], verde["color"], verde["name"]) == (
        "nuevo", "Verde", "verde", "Cazadora lana",
    )
    assert verde["url"] == "https://tienda.test/verde" and len(verde["photos"]) == 2 and verde["sizes"]
    assert [c["current"] for c in verde["colors"]] == [False, False, True] and verde["saved"] is None
    assert _status(primero) == "variante"
    siguiente = client.get("/api/shop/next").json()
    assert siguiente["remaining"] == 2 and siguiente["item"]["product_ref"] in ("zara:verde", "zara:camisa")

    # Volver al color de antes es inmediato: ya se tenía.
    connector.calls.clear()
    vuelta = client.post(f"/api/shop/items/{verde['id']}/color", json={"product_ref": primero}).json()
    assert (vuelta["id"], vuelta["status"], connector.calls) == (item["id"], "nuevo", [])
    assert _status("zara:verde") == "variante"
    client.post(f"/api/shop/items/{item['id']}/color", json={"product_ref": "zara:verde"})
    assert connector.calls == [] and (_status("zara:verde"), _status(primero)) == ("nuevo", "variante")

    # El «me gusta» es al color que se ve. El apartado no cuenta como descartado ni vuelve a salir.
    after = client.post(f"/api/shop/items/{verde['id']}/like").json()
    assert after["item"]["product_ref"] == "zara:camisa" and after["remaining"] == 1 and after["can_undo"] is True
    assert [i["product_ref"] for i in client.get("/api/shop/liked").json()] == ["zara:verde"]
    assert set(_taste().colors) == {"verde"} and _status(primero) == "variante"
    # «Ver más» tampoco trae el otro color del catálogo como propuesta aparte, ni gasta peticiones en él.
    connector.calls.clear()
    assert _more()["added"] == 0 and connector.asked("detalle") == []
    assert len(_items("candidato")) == 1 and client.get("/api/shop/next").json()["more"] == 0

    # «Volver» devuelve el verde, que es el que se valoró.
    assert client.post("/api/shop/undo").json()["item"]["product_ref"] == "zara:verde"
    client.post(f"/api/shop/items/{verde['id']}/dislike")
    assert set(_taste().colors) == {"verde"}  # el descarte es del verde; del apartado no se dice nada

    # Con la siguiente consulta, el color apartado se va con su tanda, sin fotos y sin contar.
    connector.products["camisas"] = []
    _refresh(INVIERNO + timedelta(days=7))
    apartado = next(i for i in _items() if i.product_ref == primero)
    assert (apartado.status, apartado.photos, apartado.liked_at) == ("caducado", [], None)
    assert set(_taste().colors) == {"verde"}


def test_un_color_elegido_fuera_de_descubrir_llega_como_buscado_y_se_puede_guardar(client, tienda):
    connector = tienda(camisas=[product("blanca", "chaqueta", "blanco", name="Cazadora lana")])
    _colores(connector, ("blanca", "Blanco roto", "#f0ede4"), ("negra", "Negro", "#111111"), ("gris", "Gris", "#888888"))
    _refresh()
    blanca = client.get("/api/shop/next").json()["item"]
    client.post(f"/api/shop/items/{blanca['id']}/like")
    color = f"/api/shop/items/{blanca['id']}/color"

    # Desde «Me gustan» se mira el negro: no cambia nada de lo guardado ni enseña nada.
    negra = client.post(color, json={"product_ref": "zara:negra"}).json()
    assert (negra["status"], negra["saved"], negra["store_color"]) == ("buscado", None, "Negro")
    assert negra["price_cents"] == blanca["price_cents"] and negra["reasons"]
    assert [i["product_ref"] for i in client.get("/api/shop/liked").json()] == ["zara:blanca"]
    assert set(_taste().colors) == {"blanco"} and client.get("/api/shop/next").json()["item"] is None
    # Pedir el mismo color (o el que ya se ve) no vuelve a bajar nada; el guardado se devuelve tal cual.
    connector.calls.clear()
    assert client.post(color, json={"product_ref": "zara:negra"}).json()["id"] == negra["id"]
    assert client.post(color, json={"product_ref": "zara:blanca"}).json()["id"] == blanca["id"]
    mismo = client.post(f"/api/shop/items/{negra['id']}/color", json={"product_ref": "zara:blanca"}).json()
    assert (mismo["id"], mismo["status"], mismo["saved"], connector.calls) == (blanca["id"], "gustado", "gustado", [])

    # «Me gusta» al negro guarda el negro, además del blanco.
    assert client.post(f"/api/shop/items/{negra['id']}/like").status_code == 200
    assert {i["product_ref"] for i in client.get("/api/shop/liked").json()} == {"zara:blanca", "zara:negra"}

    # Lo que no se puede: un color que no es de esta prenda, uno que ya no está y la tienda caída.
    assert client.post(color, json={"product_ref": "zara:otra"}).status_code == 404
    connector.gone.add("gris")
    assert client.post(color, json={"product_ref": "zara:gris"}).status_code == 404
    connector.gone.clear()
    connector.details["gris"] = ShopDetail(price_cents=None, sizes=[], photo_urls=[])  # sin foto de producto
    assert client.post(color, json={"product_ref": "zara:gris"}).status_code == 404
    connector.details["gris"] = ShopDetail(
        price_cents=4995, sizes=[{"name": "L", "in_stock": True}], photo_urls=["https://fotos.test/gris-e1.jpg"],
    )
    connector.download = lambda url: (_ for _ in ()).throw(ShopError("HTTP 403 al bajar la foto"))
    caida = client.post(color, json={"product_ref": "zara:gris"})
    assert caida.status_code == 503 and "Zara no responde" in caida.json()["detail"] and _status("zara:gris") is None
    assert client.post("/api/shop/items/999/color", json={"product_ref": "zara:gris"}).status_code == 404

    # Un color buscado con el que no se hace nada se limpia solo, como cualquier «buscado».
    del connector.download
    gris = client.post(color, json={"product_ref": "zara:gris"}).json()
    assert (gris["status"], gris["price_cents"], gris["sizes"]) == ("buscado", 4995, [{"name": "L", "in_stock": True}])
    with SessionLocal() as db:
        assert shopping.clean_lookups(db, now=now_utc() + timedelta(hours=25)) == 1
    assert _status("zara:gris") is None and not storage.exists(gris["photos"][0]["id"])


def test_los_colores_de_lo_guardado_antes_se_rellenan_la_primera_vez_que_se_piden(client, tienda):
    connector = tienda(camisas=[product("blanca", "chaqueta", "blanco")])
    _refresh()
    item = client.get("/api/shop/next").json()["item"]
    with SessionLocal() as db:  # como los guardados antes de este cambio: sin saber sus colores
        db.get(ShopItem, item["id"]).siblings = None
        db.commit()
    assert client.get("/api/shop/next").json()["item"]["colors"] is None

    # Si la tienda falla, se queda sin saber y se puede volver a intentar.
    _colores(connector, ("blanca", "Blanco", "#ffffff"), ("negra", "Negro", "#111111"))
    connector.calls.clear()
    connector.detail = lambda store_data: (_ for _ in ()).throw(ShopError("HTTP 403"))
    assert client.post(f"/api/shop/items/{item['id']}/colors").json()["colors"] is None
    del connector.detail

    filled = client.post(f"/api/shop/items/{item['id']}/colors").json()
    assert [c["name"] for c in filled["colors"]] == ["Blanco", "Negro"] and connector.asked("detalle") == ["blanca"]
    assert filled["status"] == "nuevo" and len(filled["photos"]) == 2  # no toca nada más
    # Ya se saben: no se vuelve a preguntar a la tienda.
    assert client.post(f"/api/shop/items/{item['id']}/colors").json()["colors"] == filled["colors"]
    assert connector.asked("detalle") == ["blanca"]
    assert client.get("/api/shop/next").json()["item"]["colors"] == filled["colors"]

    # Los «me gusta» se ponen al día solos en la consulta semanal, que ya pide su ficha.
    client.post(f"/api/shop/items/{item['id']}/like")
    with SessionLocal() as db:
        db.get(ShopItem, item["id"]).siblings = None
        db.commit()
    _refresh(INVIERNO + timedelta(days=7))
    assert [c["name"] for c in client.get("/api/shop/liked").json()[0]["colors"]] == ["Blanco", "Negro"]
