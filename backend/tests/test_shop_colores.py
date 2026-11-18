"""La familia de colores de un producto (los circulitos de Compras). Sin red: las fichas de Courir se
montan con los enlaces que tenían las de verdad el 19-11-2026 (qué ficha enlaza a cuáles), que es donde
se vieron los fallos: la Dunk Low gris enseñaba 10 «colores» y la beige 2, y desde una Air Force 1 Low
se llegaba a 41 productos de toda la línea, uno de ellos sin foto que se pudiera enseñar."""
import json
from datetime import datetime, timezone

import pytest

from app.db import SessionLocal
from app.models import ShopItem
from app.services import shopping, shops, storage
from app.services.shops import ShopDetail, courir, fetch

HOY = datetime.now(timezone.utc).date()

# Dirección (sin el número) de cada producto de Courir que sale en estos tests.
DUNK = "nike-dunk-low"
AF1 = "nike-air-force-1-low"
MODELOS = {
    # Dunk Low: la ficha de la gris enlaza estos diez; la beige y la blanca, solo a la gris y a sí mismas.
    "1515649": DUNK, "1600832": DUNK, "1600880": DUNK, "1603663": DUNK, "1609373": DUNK,
    "1488649": "nike-dunk-low-panda", "1606574": "nike-dunk-low-gore-tex", "1609376": "nike-dunk-low-corduroy",
    "1610376": "nike-dunk-low-retro", "1610550": "nike-dunk-low-suede-mini-swoosh",
    # Air Force 1: la Low beige enlaza cuatro; la Luxe negra, la línea entera (aquí, una parte).
    "1603614": AF1, "1227773": AF1, "1198486": AF1, "1610321": AF1,
    "1462216": "nike-air-force-1-low-nubuck", "1492348": "nike-air-force-1-luxe", "1495127": "nike-air-force-1-luxe",
    "1610338": "nike-air-force-1-mid-gore-tex", "1607660": "nike-air-force-1-low-tech",
    "1610331": "nike-air-force-1-low-haloween",
}
COLORES = {
    "1515649": "Gris", "1600832": "Blanc", "1600880": "Beige", "1603663": "Gris", "1609373": "Beige",
    "1488649": "Blanc", "1606574": "Blanc", "1609376": "Kaki", "1610376": "Blanc", "1610550": "Ecru",
    "1603614": "Beige", "1227773": "Noir", "1198486": "Blanc", "1610321": "Gris", "1462216": "Marron",
    "1492348": "Noir", "1495127": "Blanc", "1610338": "Noir", "1607660": "Blanc", "1610331": "Marron",
}
ENLACES = {
    "1515649": ["1515649", "1488649", "1600832", "1600880", "1603663", "1606574", "1609373", "1609376", "1610376",
                "1610550"],
    "1600880": ["1600880", "1515649"],
    "1600832": ["1600832", "1515649"],
    "1603614": ["1603614", "1227773", "1462216", "1492348"],
    "1492348": ["1492348", "1603614", "1198486", "1495127", "1607660", "1610321", "1462216", "1610331", "1227773",
                "1610338"],
    "1462216": ["1462216", "1603614", "1198486", "1495127", "1610338", "1227773", "1492348"],
    "1227773": ["1227773", "1198486", "1603614", "1492348", "1610338"],
}


def _url(sku: str) -> str:
    return f"https://www.courir.com/fr/p/{MODELOS[sku]}-{sku}.html"


def _ficha(sku: str, nombre: str = "DUNK LOW", precio: int = 120, formato: str = "jpg") -> str:
    """Una ficha de Courir con lo que lee el conector: datos del producto, color, tallas y el bloque
    «Couleur» con sus enlaces. `formato`: la extensión de las fotos (alguna ficha antigua las tiene en png)."""
    fotos = [
        f"https://www.courir.com/on/demandware.static/-/Sites-master-catalog-courir/default/dw1/images/hi-res/"
        f"00{sku}_10{n}.{formato}?sw=1000&sh=1000&sm=fit"
        for n in (1, 2, 3, 4, 5)
    ]
    producto = {
        "@context": "https://schema.org", "@type": "Product", "name": nombre, "sku": sku, "image": fotos,
        "brand": {"@type": "Brand", "name": "NIKE"}, "description": "Une icône.",
        "offers": {"@type": "Offer", "url": _url(sku), "price": precio, "availability": "https://schema.org/InStock"},
    }
    enlaces = "".join(
        f'<li class="productlink-link"> <a href="{_url(otro)}" title="Couleur : {COLORES[otro]}" '
        f'aria-label="x" data-masterid="{otro}"> <img src="/x.jpg" /> </a> </li>'
        for otro in ENLACES.get(sku, [sku])
    )
    gtm = json.dumps({"brand": "NIKE", "name": nombre, "sku": sku, "supplier_id": f"XX{sku[-4:]}-100"})
    return (
        f'<html><script type="application/ld+json">{json.dumps(producto)}</script>'
        f"<button title='S&eacute;lectionner Taille: 42' data-lgimg='' data-is-available=\"true\"> 42 </button>"
        f'<p><span class="title-text">Couleur</span> <span class="color-text">{COLORES[sku].lower()}/blanc</span></p>'
        f'<ul class="productlinks-link-container" id="js_productlinks">{enlaces}</ul>'
        f"<script>var data = {{ product: JSON.parse('{gtm}') }};</script></html>"
    )


@pytest.fixture
def courir_falso(monkeypatch, photo_bytes):
    """El conector de Courir de verdad con las páginas servidas desde aquí. Devuelve lo que se ha pedido."""
    pedidas: list[str] = []
    fichas: dict[str, str] = {}

    def fake_get(self, url, accept=None, pause=None):
        pedidas.append(url)
        if "/images/" in url:
            return fetch.Page(200, photo_bytes)
        sku = url.rsplit("-", 1)[-1].removesuffix(".html")
        if sku in fichas:
            return fetch.Page(200, fichas[sku].encode())
        return fetch.Page(404, b"")

    monkeypatch.setattr(courir.CourirConnector, "_get", fake_get)
    shops.CONNECTORS["courir"]._pages = {}
    pedidas_y_fichas = (pedidas, fichas)
    yield pedidas_y_fichas
    shops.CONNECTORS["courir"]._pages = {}


def _guardar(sku: str, status: str, siblings: list[dict] | None, photo_bytes: bytes | None = None, **extra) -> int:
    """Una zapatilla de Courir ya guardada (con su foto, si se da) y la lista de colores que se indique."""
    with SessionLocal() as db:
        row = ShopItem(
            store="courir", product_ref=f"courir:{sku}", name=extra.pop("name", "Dunk Low"), brand="Nike",
            price_cents=12000, url=_url(sku), store_color=f"{COLORES[sku].lower()}/blanc", section="sneakers",
            type="zapatillas", category="calzado", color="gris", pattern="liso", style="casual",
            season="todo_el_ano", status=status, batch=HOY, siblings=siblings,
            photos=[storage.save_upload(photo_bytes, "courir.jpg")] if photo_bytes else [],
            store_data={"sku": sku, "url": _url(sku), "model": None}, **extra,
        )
        db.add(row)
        db.commit()
        return row.id


def _enlazados(sku: str) -> list[dict]:
    """La lista de colores tal como la guardaban las versiones anteriores: todo lo que enlaza la ficha."""
    return sorted(
        ({"product_ref": f"courir:{otro}", "name": COLORES[otro], "hex": None, "url": _url(otro),
          "store_data": {"sku": otro, "url": _url(otro), "model": None}} for otro in ENLACES[sku]),
        key=lambda s: s["product_ref"],
    )


def _circulitos(item: dict) -> list[str]:
    return [c["product_ref"].split(":")[1] + ("*" if c["current"] else "") for c in item["colors"]]


def _estado(sku: str) -> str | None:
    with SessionLocal() as db:
        row = db.query(ShopItem).filter_by(product_ref=f"courir:{sku}").first()
        return row.status if row else None


# ---------- Qué es un color de la misma zapatilla


def test_en_courir_solo_es_otro_color_lo_que_comparte_direccion_salvo_el_numero():
    assert courir.same_model(_url("1603614"), _url("1227773"))
    assert not courir.same_model(_url("1603614"), _url("1462216"))  # la de nobuk es otra zapatilla
    assert not courir.same_model(_url("1603614"), _url("1492348"))  # y la Luxe, otra (y más cara)
    assert not courir.same_model("https://www.courir.com/fr/c/homme/", "https://www.courir.com/fr/c/homme/")
    assert not courir.same_model(None, _url("1227773"))

    # La ficha de la Luxe negra enlaza como «colores» toda la línea Air Force 1: solo vale la otra Luxe.
    _info, luxe = courir.parse_product_page(_ficha("1492348", "AIR FORCE 1 LUXE", 140))
    assert [s["product_ref"] for s in luxe.siblings] == ["courir:1492348", "courir:1495127"]
    # La de nobuk enlaza a otros modelos y a ninguna de nobuk: solo existe en ese color.
    _info, nobuk = courir.parse_product_page(_ficha("1462216", "AIR FORCE 1 LOW"))
    assert nobuk.siblings == []
    # La Dunk Low gris: de diez enlaces, cinco son Dunk Low (las demás: Panda, Gore-Tex, Corduroy, Retro…).
    _info, gris = courir.parse_product_page(_ficha("1515649"))
    assert [s["product_ref"].split(":")[1] for s in gris.siblings] == ["1515649", "1600832", "1600880", "1603663", "1609373"]


# ---------- Elegir un color y volver


def test_al_elegir_un_color_y_volver_los_circulitos_son_los_mismos(client, courir_falso, photo_bytes):
    """Dunk Low: la gris conoce cuatro colores más; la ficha de la beige solo nombra a la gris. Se elija
    el que se elija, los dos enseñan la misma familia, y volver al de antes no pide nada a la tienda."""
    pedidas, fichas = courir_falso
    fichas.update({"1515649": _ficha("1515649"), "1600880": _ficha("1600880", precio=130)})
    _info, detalle = courir.parse_product_page(fichas["1515649"])
    gris_id = _guardar("1515649", shopping.NEW, detalle.siblings, photo_bytes)
    familia = ["1515649", "1600832", "1600880", "1603663", "1609373"]

    beige = client.post(f"/api/shop/items/{gris_id}/color", json={"product_ref": "courir:1600880"})
    assert beige.status_code == 200, beige.text
    beige = beige.json()
    assert (beige["status"], beige["price_cents"], beige["name"]) == ("nuevo", 13000, "Dunk Low")
    assert _circulitos(beige) == ["1515649", "1600832", "1600880*", "1603663", "1609373"]
    assert _estado("1515649") == "variante" and [u for u in pedidas if u.endswith(".html")] == [_url("1600880")]

    # Volver a la gris: ya se tenía, con sus fotos. Ni una petición, y los mismos circulitos.
    pedidas.clear()
    gris = client.post(f"/api/shop/items/{beige['id']}/color", json={"product_ref": "courir:1515649"}).json()
    assert (gris["id"], gris["status"], pedidas) == (gris_id, "nuevo", [])
    assert _circulitos(gris) == ["1515649*", "1600832", "1600880", "1603663", "1609373"]
    assert _estado("1600880") == "variante"
    otra_vez = client.post(f"/api/shop/items/{gris_id}/color", json={"product_ref": "courir:1600880"}).json()
    assert (otra_vez["id"], pedidas) == (beige["id"], [])
    assert [c["product_ref"].split(":")[1] for c in otra_vez["colors"]] == familia

    # La consulta semanal relee la ficha de la beige, que sigue nombrando solo dos: no pierde los demás.
    with SessionLocal() as db:
        row = db.get(ShopItem, beige["id"])
        shopping._apply_detail(row, courir.parse_product_page(fichas["1600880"])[1])
        db.commit()
        assert [s["product_ref"].split(":")[1] for s in row.siblings] == familia


def test_las_listas_guardadas_con_toda_la_linea_se_leen_solo_con_el_mismo_modelo(client, courir_falso, photo_bytes):
    """Lo que quedó guardado antes: la Air Force 1 Low beige con la de nobuk y la Luxe entre sus colores,
    y la Luxe con la línea entera. Al leerlo solo cuenta el mismo modelo, sin tocar la tienda."""
    pedidas, _fichas = courir_falso
    beige_id = _guardar("1603614", shopping.NEW, _enlazados("1603614"), photo_bytes, name="Air Force 1 Low")
    luxe_id = _guardar("1492348", shopping.VARIANT, _enlazados("1492348"), photo_bytes, name="Air Force 1 Low")
    with SessionLocal() as db:
        beige, luxe = db.get(ShopItem, beige_id), db.get(ShopItem, luxe_id)
        assert [c["product_ref"] for c in shopping.colors_of(beige)] == ["courir:1227773", "courir:1603614"]
        assert [c["product_ref"] for c in shopping.colors_of(luxe)] == ["courir:1492348", "courir:1495127"]
        # Una sola en su modelo (la de Halloween): sin circulitos.
        sola = db.get(ShopItem, _guardar("1610331", shopping.NEW, _enlazados("1492348"), name="Air Force 1 Low"))
        assert shopping.colors_of(sola) == []
        # Al montar tandas, lo que no es el mismo modelo no cuenta como «otro color de algo que ya se enseña».
        _shown, family = shopping._shown_this_round(db)
        assert family == {"courir:1227773", "courir:1495127"}

    # La Luxe ya no es un color de la Low: no se puede llegar a ella desde su tarjeta.
    luxe = client.post(f"/api/shop/items/{beige_id}/color", json={"product_ref": "courir:1492348"})
    assert luxe.status_code == 404 and pedidas == []


def test_un_color_sin_foto_que_ensenar_se_quita_y_no_se_vuelve_a_pedir(client, courir_falso, photo_bytes):
    """Lo que pasó con la marrón de nobuk («Ese color ya no está en la tienda»): la ficha existe y hay
    tallas, pero sus fotos no son las de producto que sabe leer el conector (están en png). Aquí, con un
    color del mismo modelo: se dice lo que pasa de verdad y el circulito se quita."""
    pedidas, fichas = courir_falso
    fichas["1227773"] = _ficha("1227773", "AIR FORCE 1 LOW", formato="png")
    familia = [s for s in _enlazados("1492348") if courir.same_model(_url("1603614"), s["url"])]
    assert [s["product_ref"].split(":")[1] for s in familia] == ["1198486", "1227773", "1603614", "1610321"]
    beige_id = _guardar("1603614", shopping.NEW, familia, photo_bytes, name="Air Force 1 Low")
    gris_id = _guardar("1610321", shopping.CANDIDATE, familia, name="Air Force 1 Low")

    fallo = client.post(f"/api/shop/items/{beige_id}/color", json={"product_ref": "courir:1227773"})
    assert fallo.status_code == 404 and fallo.json()["detail"] == "Ese color no tiene foto de producto en la tienda"
    assert _estado("1227773") is None and _estado("1603614") == "nuevo"
    with SessionLocal() as db:
        for item_id in (beige_id, gris_id):  # fuera de todos los que lo nombraban
            assert "courir:1227773" not in [s["product_ref"] for s in db.get(ShopItem, item_id).siblings]
    # La tarjeta pide sus colores otra vez (lo hace sola tras el error) y el circulito ya no está.
    pedidas.clear()
    tarjeta = client.post(f"/api/shop/items/{beige_id}/colors").json()
    assert _circulitos(tarjeta) == ["1198486", "1603614*", "1610321"] and pedidas == []
    assert client.post(f"/api/shop/items/{beige_id}/color", json={"product_ref": "courir:1227773"}).status_code == 404
    assert pedidas == []

    # Una ficha que ya no existe (404): lo mismo, con su mensaje.
    fuera = client.post(f"/api/shop/items/{beige_id}/color", json={"product_ref": "courir:1198486"})
    assert fuera.status_code == 404 and fuera.json()["detail"] == "Ese color ya no está en la tienda"
    assert _circulitos(client.post(f"/api/shop/items/{beige_id}/colors").json()) == ["1603614*", "1610321"]


# ---------- Las demás tiendas


def _prenda(ref: str, status: str, siblings, **extra) -> ShopItem:
    return ShopItem(
        store="pullandbear", product_ref=f"pullandbear:{ref}", name="Pull basique", price_cents=2999,
        url=f"https://www.pullandbear.com/fr/{ref}", type="jersey", category="parte_superior", color="verde",
        pattern="liso", style="casual", season="invierno", status=status, batch=HOY, siblings=siblings, **extra,
    )


def _color(ref: str, **extra) -> dict:
    return {"product_ref": f"pullandbear:{ref}", "name": ref, "hex": None, **extra}


def test_en_las_demas_tiendas_manda_la_ficha_y_al_elegir_se_comparte_la_familia(client):
    ahora = datetime.now(timezone.utc)
    with SessionLocal() as db:
        verde = _prenda("9-500", shopping.LIKED, [_color("9-500"), _color("9-800", name_es="Negro"), _color("9-250")],
                        liked_at=ahora, store_color="Vert")
        # El negro se guardó sabiendo menos colores, y sin nombrarse a sí mismo.
        negro = _prenda("9-800", shopping.LIKED, [_color("9-500")], liked_at=ahora, store_color="Noir")
        db.add_all([verde, negro])
        db.commit()
        elegido = shopping.switch_color(db, verde, "pullandbear:9-800")
        todos = ["pullandbear:9-250", "pullandbear:9-500", "pullandbear:9-800"]
        assert elegido.id == negro.id
        assert [s["product_ref"] for s in elegido.siblings] == [s["product_ref"] for s in verde.siblings] == todos
        # El color que se ve siempre está entre los circulitos, y marcado; la traducción no se pierde.
        assert [(c["product_ref"], c["current"]) for c in shopping.colors_of(elegido)] == [
            (todos[0], False), (todos[1], False), (todos[2], True),
        ]
        assert next(s for s in elegido.siblings if s["product_ref"] == todos[2])["name_es"] == "Negro"
        assert shopping.switch_color(db, elegido, "pullandbear:9-500").id == verde.id

        # La ficha de Pull&Bear nombra todos sus colores: si deja de nombrar uno, es que lo ha retirado.
        ficha = ShopDetail(price_cents=None, sizes=[], photo_urls=[], siblings=[_color("9-500"), _color("9-800")])
        shopping._apply_detail(verde, ficha)
        assert [s["product_ref"] for s in verde.siblings] == ["pullandbear:9-500", "pullandbear:9-800"]
        assert verde.siblings[1]["name_es"] == "Negro"
