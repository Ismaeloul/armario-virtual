"""Compras: las fotos que faltan en lo guardado (tiendas de navegador) y las ofertas (precio de antes tachado).

Todo sin red ni navegador: un navegador falso que responde con las fichas guardadas en `fixtures/`, y esas
mismas fichas con el precio de antes cuando hace falta una rebajada que no estaba en los datos."""
import copy
import json
from datetime import timedelta

import pytest
from conftest import FakeAnalyzer  # noqa: F401  (mismo patrón que los otros tests de Compras)
from test_shop import FIXTURES, INVIERNO, _items, _refresh, product, tienda  # noqa: F401  (fixture)
from test_shop_navegador import FakeJDSession, _json, sin_navegador  # noqa: F401  (fixture)

from app import config
from app.db import SessionLocal
from app.models import ShopItem, now_utc
from app.services import shopping, shops
from app.services.shops import ShopDetail, ShopError, bershka, bonobo, browser, carhartt, cos, courir, footlocker
from app.services.shops import inditex, jdsports, jules, nike, sizeofficial, snipes, uniqlo, weekday, zara


def _text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def sin_intentos():
    """Los intentos fallidos de bajar fotos se recuerdan en memoria: cada test empieza de cero."""
    shopping._photo_tries.clear()
    yield
    shopping._photo_tries.clear()


# ---------- Tarea 1: las fotos que faltan


JD_ID = "19715952"
JD_SLUG = "blanc-nike-air-force-1-07-lv8"
JD_PAGE = jdsports.product_url(JD_SLUG, JD_ID)


def _jd_guardado(status: str = "gustado", **fields) -> int:
    """El caso real: un «me gusta» de JD Sports guardado desde el buscador, de una consulta antigua (sin la
    instantánea del listado), sin fotos ni tallas."""
    with SessionLocal() as db:
        row = ShopItem(
            store="jdsports", product_ref=fields.pop("product_ref", f"jdsports:{JD_ID}"), name="Air Force 1 '07 LV8",
            price_cents=12000, url=JD_PAGE, store_color="Blanc", section="baskets", type="zapatillas",
            category="calzado", color="blanco", pattern="liso", style="casual", season="todo_el_ano", status=status,
            batch=INVIERNO, liked_at=now_utc() if status == "gustado" else None, photos=[], sizes=[],
            store_data=fields.pop("store_data", {"id": JD_ID, "slug": JD_SLUG, "ref": None, "age": 12}),
            first_seen_at=now_utc(), **fields,
        )
        db.add(row)
        db.commit()
        return row.id


def _jd_ficha(was: int | None = None):
    product_ = copy.deepcopy(_json("jd_producto.json"))
    product_["id"] = JD_ID
    if was is not None:
        product_["minWasPrice"] = {"centAmount": was, "currencyCode": "EUR"}
    return {"props": {"pageProps": {"product": product_}}}


@pytest.fixture
def jd(monkeypatch, photo_bytes):
    """JD Sports con su navegador de mentira (que solo conoce la ficha del caso real) y las fotos de su CDN."""
    monkeypatch.setattr(browser, "missing", lambda: None)
    session = FakeJDSession({JD_PAGE: (200, _jd_ficha())})
    # Solo se cambia el navegador por el falso: la sesión (`browser.session`, `active`) es la de verdad.
    monkeypatch.setattr(browser, "require", lambda store: session)
    downloaded = []
    monkeypatch.setattr(jdsports.JDSportsConnector, "download", lambda self, url: downloaded.append(url) or photo_bytes)
    session.downloaded = downloaded
    return session


def test_un_me_gusta_sin_foto_de_jd_la_consigue_con_su_ficha_en_el_navegador(client, jd):
    item_id = _jd_guardado()
    before = client.get("/api/shop/liked").json()[0]
    assert before["photos"] == [] and before["photo_pending"]  # Me gustan lo dice
    with SessionLocal() as db:
        assert [i.id for i in shopping.missing_photos(db)] == [item_id]
        result = shopping.fetch_missing_photos(db)
    assert result["photos"] == 1 and result["failed"] == 0
    assert jd.opened == [JD_PAGE]  # solo esa ficha: ni listados ni nada más
    assert all(url.startswith("https://i8.amplience.net/") for url in jd.downloaded)
    after = client.get(f"/api/shop/items?ids={item_id}").json()[0]
    assert len(after["photos"]) >= 1 and not after["photo_pending"]
    assert after["sizes"] and after["status"] == "gustado"
    with SessionLocal() as db:
        assert shopping.missing_photos(db) == []  # ya no queda nada que bajar
        shopping.fetch_missing_photos(db)
    assert jd.opened == [JD_PAGE]  # y no se vuelve a pedir


def test_fuera_del_trabajo_en_segundo_plano_jd_no_abre_el_navegador(client, monkeypatch, jd):
    """La ficha de verdad solo se pide dentro de una sesión (el trabajo de las fotos la abre); una petición HTTP
    normal nunca: el buscador deja la tarjeta con «foto pendiente»."""
    monkeypatch.setattr(jdsports.browser, "active", lambda: False)
    with pytest.raises(shops.NeedsBrowser):
        jdsports.JDSportsConnector().detail({"id": JD_ID, "slug": JD_SLUG})
    assert jd.opened == []


def test_sin_bucle_automatico_no_se_lanza_nada_solo(client, jd):
    assert not config.SHOP_AUTO
    _jd_guardado()
    assert shopping.photos_soon() is False
    assert jd.opened == []


def test_si_la_tienda_bloquea_se_para_hasta_manana_y_el_panel_lo_dice(client, jd):
    first, second = _jd_guardado(), _jd_guardado(status="buscado", product_ref="jdsports:1", store_data={"id": "1"})
    jd.pages[JD_PAGE] = lambda: browser.block("jdsports", browser.BLOCKED_TEXT)
    with SessionLocal() as db:
        result = shopping.fetch_missing_photos(db)
        assert result["photos"] == 0 and result["failed"] == 1
        assert jd.opened == [JD_PAGE]  # tras el bloqueo, ni una ficha más
        assert shopping.blocked_today(db, "jdsports")
        assert shopping.missing_photos(db) == []  # hoy ya no se intenta
    panel = next(s for s in client.get("/api/shop/state").json()["stores"] if s["key"] == "jdsports")
    assert panel["status"]["error"].startswith("JD Sports: la tienda ha bloqueado el acceso")
    liked = client.get(f"/api/shop/items?ids={first},{second}").json()
    assert [i["photo_pending"] for i in liked] == [True, True]


def test_un_fallo_se_reintenta_mas_tarde_sin_insistir(client, jd):
    item_id = _jd_guardado()
    jd.pages[JD_PAGE] = ShopError("la página no cargó (TimeoutError)")
    with SessionLocal() as db:
        assert shopping.fetch_missing_photos(db)["failed"] == 1
        assert shopping.missing_photos(db) == []  # recién fallado: el bucle no lo vuelve a pedir enseguida
        later = now_utc() + shopping.PHOTO_RETRY + timedelta(minutes=1)
        assert [i.id for i in shopping.missing_photos(db, later)] == [item_id]
        # Cada fallo dobla la espera.
        shopping._photo_failed(item_id, later)
        assert shopping.missing_photos(db, later + shopping.PHOTO_RETRY + timedelta(minutes=1)) == []
    assert not shopping._photo_wait(item_id, later + shopping.PHOTO_RETRY_MAX)


def test_no_se_toca_una_tienda_que_se_esta_consultando(client, monkeypatch, jd):
    _jd_guardado()
    monkeypatch.setattr(shopping, "_crawling_stores", lambda: {"jdsports"})
    with SessionLocal() as db:
        assert shopping.missing_photos(db) == []
        shopping.fetch_missing_photos(db)
    assert jd.opened == []


def test_si_empieza_una_consulta_se_para_entre_ficha_y_ficha(client, jd):
    _jd_guardado()
    with SessionLocal() as db:
        result = shopping.fetch_missing_photos(db, stop=lambda: True)
    assert result["photos"] == 0 and jd.opened == []


def test_si_mientras_tanto_se_quita_de_me_gustan_las_fotos_no_se_quedan(client, monkeypatch, jd):
    item_id = _jd_guardado()
    deleted = []
    monkeypatch.setattr(shopping.storage, "delete", lambda photo_id: deleted.append(photo_id))

    def quitado():
        with SessionLocal() as other:
            shopping.remove_liked(other, other.get(ShopItem, item_id))
        return 200, _jd_ficha()

    jd.pages[JD_PAGE] = quitado
    with SessionLocal() as db:
        assert shopping.fetch_missing_photos(db)["photos"] == 0
        assert db.get(ShopItem, item_id).photos == []
    assert deleted  # las bajadas se borran: no queda ninguna suelta


def test_el_endpoint_de_items_concretos(client):
    ids = [_jd_guardado(), _jd_guardado(status="buscado", product_ref="jdsports:2", store_data={"id": "2"})]
    answer = client.get(f"/api/shop/items?ids={ids[1]},{ids[0]},999999")
    assert [i["id"] for i in answer.json()] == [ids[1], ids[0]]
    assert client.get("/api/shop/items?ids=1;DROP").status_code == 422


# ---------- Tarea 2: lo que dice cada tienda


def test_inditex_old_price_de_las_tallas(monkeypatch):
    data = copy.deepcopy(_json("bershka_sweats.json")["products"][:1])
    plain = inditex.parse_products(data, bershka.SITE, "sweats-n3714")[0]
    assert plain.old_price_cents is None and plain.old_price_known
    summary = (data[0].get("bundleProductSummaries") or [data[0]])[0]
    color = summary["detail"]["colors"][0]
    for size in color["sizes"]:
        size["price"], size["oldPrice"] = "3599", "5999"  # como en Stradivarius, la misma plataforma
    sale = inditex.parse_products(data, bershka.SITE, "sweats-n3714")[0]
    assert (sale.price_cents, sale.old_price_cents) == (3599, 5999)
    detail = inditex.detail_from(bershka.SITE, sale.store_data)
    assert (detail.price_cents, detail.old_price_cents, detail.old_price_known) == (3599, 5999, True)
    # Una instantánea guardada antes de las ofertas no dice nada de la rebaja.
    old_snap = copy.deepcopy(sale.store_data)
    for c in old_snap["snap"]["colors"]:
        c.pop("old")
    assert not inditex.detail_from(bershka.SITE, old_snap).old_price_known


def test_jd_was_price_en_el_listado_y_min_was_price_en_la_ficha():
    hit = {**_json("jd_listado.json")["hits"][0], "price": 50, "wasPrice": 130}
    sale = jdsports.parse_listing({"hits": [hit]}, "baskets")[0]
    assert (sale.price_cents, sale.old_price_cents) == (5000, 13000)
    plain = jdsports.parse_listing({"hits": _json("jd_listado.json")["hits"][:1]}, "baskets")[0]
    assert plain.old_price_cents is None and plain.old_price_known
    assert jdsports.parse_product(_jd_ficha(was=20000)).old_price_cents == 20000
    assert jdsports.parse_product(_jd_ficha(was=17000)).old_price_cents is None  # igual que el de ahora: no es oferta
    assert jdsports.parse_product(_jd_ficha()).old_price_cents is None


def test_nike_initial_price():
    products = nike.parse_wall(nike.wall(_json("nike_listado.json"))["productGroupings"], "chaussures")
    sale = next(p for p in products if p.price_cents == 9599)
    assert sale.old_price_cents == 15999 and sale.old_price_known
    _item, detail = nike.parse_product_page(_json("nike_ficha.json"))
    assert (detail.price_cents, detail.old_price_cents) == (9599, 15999)


def test_snipes_before_sale_with_tax():
    item = copy.deepcopy(_json("snipes_listado.json")["products"][0])
    assert snipes.make_product(item, "chaussures").old_price_cents is None
    item["priceRange"]["min"].update(withTax=8000, beforeSaleWithTax=11499)
    sale = snipes.make_product(item, "chaussures")
    assert (sale.price_cents, sale.old_price_cents) == (8000, 11499)


def test_size_compare_at_price_en_listado_y_ficha():
    data = copy.deepcopy(_json("size_listado.json"))
    plain = sizeofficial.parse_listing(data, "chaussures-hommes")[0]
    assert plain.old_price_cents is None and plain.old_price_known
    doc = sizeofficial.listing_response(data)["docs"][0]
    doc["sale_price"] = 135.0
    for variant in doc["variants"]:
        variant["compareAtPrice"] = [180.0]
    assert sizeofficial.parse_listing(data, "chaussures-hommes")[0].old_price_cents == 18000
    page = _text("size_ficha.html")
    assert sizeofficial.parse_product_page(page).old_price_cents is None
    sale = sizeofficial.parse_product_page(page.replace('"compare_at_price": 14000', '"compare_at_price": 18000'))
    assert (sale.price_cents, sale.old_price_cents, sale.old_price_known) == (14000, 18000, True)


def test_foot_locker_list_price_en_la_ficha_y_original_price_en_el_listado():
    product_block = footlocker.block(_json("footlocker_ficha.json")["loaderData"], "product")
    info, detail = footlocker.parse_product(product_block)
    assert (detail.price_cents, detail.old_price_cents) == (15000, 18999)  # rebajada de verdad en la captura
    listing = copy.deepcopy(footlocker.block(_json("footlocker_listado.json")["loaderData"], "products"))
    assert footlocker.parse_listing(listing, "chaussures")[0].old_price_cents is None  # iguales: sin rebaja
    first = next(i for i in listing["products"] if isinstance(i, dict) and i.get("originalPrice"))
    first["price"]["value"] = 150
    assert footlocker.parse_listing(listing, "chaussures")[0].old_price_cents == 18999


def test_courir_default_price_tachado_en_el_listado_y_la_ficha_no_lo_sabe():
    products = courir.parse_grid(_text("courir_listado.html"), "sneakers")
    assert (products[0].price_cents, products[0].old_price_cents) == (15000, 21000)  # rebajada en la captura
    assert products[1].old_price_cents is None and products[1].old_price_known


def test_carhartt_discounted_price():
    tile = {"productKey": "1", "slug": "x", "fullName": "Chase Sweat Black", "colorFinishDescription": "Black",
            "productTitle": "Chase Sweat", "categoryUrlAnalytics": "sweats"}
    assert carhartt.make_product({**tile, "price": 99, "discountedPrice": "$undefined"}, "sweats").old_price_cents is None
    sale = carhartt.make_product({**tile, "price": 99, "discountedPrice": 69.3}, "sweats")
    assert (sale.price_cents, sale.old_price_cents) == (6930, 9900)


def test_sfra_price_list_en_la_ficha():
    detail = bonobo.parse_variation(_json("bonobo_variation.json")["product"])
    assert (detail.price_cents, detail.old_price_cents, detail.old_price_known) == (4199, 5999, True)
    assert jules.parse_variation(_json("jules_variation.json")["product"]).old_price_cents is None


def test_listados_de_uniqlo_weekday_y_cos():
    data = copy.deepcopy(_json("uniqlo_listado.json"))
    item = next(i for i in uniqlo_items(data))
    assert all(p.old_price_cents is None for p in uniqlo.parse_listing(data, "t-shirts")[0])
    item["prices"] = {"base": {"value": 49.9}, "promo": {"value": 39.9}}
    sale = uniqlo.parse_listing(data, "t-shirts")[0][0]
    assert (sale.price_cents, sale.old_price_cents) == (3990, 4990)

    data = copy.deepcopy(_json("weekday_listado.json"))
    assert all(p.old_price_cents is None for p in weekday.parse_listing(data, "shirts")[0])
    raw = weekday.listing_data(data)["products"][0]
    raw["pricing"].update(priceAsNumber=45, priceBeforeDiscountAsNumber=89.99, isOnSale=True)
    assert weekday.parse_listing(data, "shirts")[0][0].old_price_cents == 8999

    data = copy.deepcopy(_json("cos_listado.json"))
    assert all(p.old_price_cents is None for p in cos.parse_listing(data, "shirts")[0])
    raws = [r for r in walk(data) if isinstance(r, dict) and "priceBeforeDiscount" in r]
    raws[0]["price"]["value"] = 89
    assert any(p.old_price_cents == 12900 for p in cos.parse_listing(data, "shirts")[0])


def uniqlo_items(data):
    return [o for o in walk(data) if isinstance(o, dict) and "prices" in o and "productId" in o]


def walk(value):
    yield value
    if isinstance(value, dict):
        for inner in value.values():
            yield from walk(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from walk(inner)


def test_zara_no_dice_rebaja_hasta_verla():
    products = zara.parse_category(_json("zara_categoria_fr.json"), "homme-pantalons-l838")
    assert products and all(p.old_price_cents is None and not p.old_price_known for p in products)


# ---------- Tarea 2: cómo se guarda y se enseña


def test_el_precio_de_antes_sigue_lo_que_dice_la_tienda():
    row = ShopItem(price_cents=None, old_price_cents=None)
    shopping._set_price(row, 3599, 5999, known=True)
    assert (row.price_cents, row.old_price_cents) == (3599, 5999)
    shopping._set_price(row, 3599, None, known=False)  # una ficha que no lo sabe, mismo precio: se queda
    assert row.old_price_cents == 5999
    shopping._set_price(row, None, None, known=True)  # sin precio no se toca nada
    assert (row.price_cents, row.old_price_cents) == (3599, 5999)
    shopping._set_price(row, 3999, None, known=False)  # otro precio y nadie dice el de antes: fuera
    assert (row.price_cents, row.old_price_cents) == (3999, None)
    shopping._set_price(row, 3999, 5999, known=True)
    shopping._set_price(row, 5999, None, known=True)  # la oferta ha terminado
    assert (row.price_cents, row.old_price_cents) == (5999, None)
    shopping._set_price(row, 5999, 4000, known=True)  # «antes» más barato no es una oferta
    assert row.old_price_cents is None


def _rebajado(ref: str, price: int, old: int | None, **extra):
    item = product(ref, price=price, **extra)
    item.old_price_cents, item.old_price_known = old, True
    return item


def test_una_consulta_guarda_la_rebaja_y_la_revision_de_los_me_gusta_la_quita(client, tienda):
    zara_ = tienda(camisas=[_rebajado("c1", 1995, 2995)])
    _refresh(limit=4)
    shown = _items("nuevo")[0]
    assert (shown.price_cents, shown.old_price_cents) == (1995, 2995)
    answer = client.get("/api/shop/next").json()["item"]
    assert (answer["price_cents"], answer["old_price_cents"]) == (1995, 2995)
    client.post(f"/api/shop/items/{shown.id}/like")
    # La semana siguiente el listado ya no la trae rebajada: se ve como siempre.
    zara_.products["camisas"] = [_rebajado("c1", 2995, None)]
    _refresh(today=INVIERNO + timedelta(days=7), limit=4)
    liked = client.get("/api/shop/liked").json()[0]
    assert (liked["price_cents"], liked["old_price_cents"]) == (2995, None)
    # Y si vuelve a estarlo, con la ficha (que sí lo dice).
    zara_.products["camisas"] = []
    zara_.details["c1"] = ShopDetail(price_cents=2495, old_price_cents=2995, old_price_known=True, sizes=[
        {"name": "M", "in_stock": True}], photo_urls=["https://fotos.test/c1-e1.jpg"])
    _refresh(today=INVIERNO + timedelta(days=14), limit=4)
    liked = client.get("/api/shop/liked").json()[0]
    assert (liked["price_cents"], liked["old_price_cents"]) == (2495, 2995)


def test_el_precio_no_cuenta_para_la_nota(client):
    with SessionLocal() as db:
        context = shopping.Context.load(db)
        a = ShopItem(**_campos("a"), price_cents=1995, old_price_cents=None)
        b = ShopItem(**_campos("b"), price_cents=1995, old_price_cents=4995)
        assert context.score(a) == context.score(b)


def _campos(ref: str) -> dict:
    return dict(store="zara", product_ref=f"zara:{ref}", name="Camisa oxford", url="https://tienda.test/x",
                store_color="Blanco", section="camisas", type="camisa", category="parte_superior", color="blanco",
                pattern="liso", style="casual", season="todo_el_ano", details="", brand=None, store_data={})


def test_en_el_armario_no_sale_ningun_precio(client, tienda, analyzers):
    analyzers(FakeAnalyzer("codex", error=RuntimeError("sin IA")), FakeAnalyzer("claude", error=RuntimeError("sin IA")))
    tienda(camisas=[_rebajado("c1", 1995, 2995)])
    _refresh(limit=4)
    item = _items("nuevo")[0]
    garment = client.post(f"/api/shop/items/{item.id}/bought", json={"size": "M"}).json()
    ficha = client.get(f"/api/garments/{garment['garment_id']}").json()
    assert not any("price" in key or "precio" in key for key in ficha)


def test_el_buscador_y_el_cambio_de_color_traen_la_rebaja(client, tienda):
    connector = tienda(camisas=[product("a")])
    connector.found["3918/300"] = [_rebajado("negra", 2995, 3995, type="chaqueta", color="negro")]
    connector.family["negra"] = [
        {"product_ref": "zara:negra", "name": "Negro", "hex": None, "store_data": {"ref": "negra"}},
        {"product_ref": "zara:caqui", "name": "Caqui", "hex": None, "price_cents": 1995, "old_price_cents": 3995,
         "store_data": {"ref": "caqui"}},
    ]
    negra = client.post("/api/shop/lookup", json={"query": "3918/300"}).json()[0]
    assert (negra["price_cents"], negra["old_price_cents"]) == (2995, 3995)
    caqui = client.post(f"/api/shop/items/{negra['id']}/color", json={"product_ref": "zara:caqui"}).json()
    assert (caqui["price_cents"], caqui["old_price_cents"]) == (1995, 3995)
