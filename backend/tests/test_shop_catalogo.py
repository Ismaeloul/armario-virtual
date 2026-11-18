"""El catálogo entero, de noche y despacio: recorrido completo con topes, secciones que fallan a medias
y se retoman, la hora de la noche, la cancelación, el avance, la variedad con miles de candidatos, la
reserva de fotos, los colores de JD preparados y el buscador en lo guardado. Todo sin red ni navegador."""
import threading
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select
from test_shop import INVIERNO, FakeConnector, _items, _refresh, product, tienda  # noqa: F401  (fixture)
from test_shop_navegador import _con_sesion, _jd_listado, _json, FakeJDSession, JD_BASKETS  # noqa: F401
from test_shop_navegador import sin_navegador  # noqa: F401  (fixture: ningún test abre Chromium)

from app.db import SessionLocal
from app.models import ShopItem
from app.services import shopping, shops
from app.services.shops import BlockedError, ShopError, browser, crawl, estimate, jdsports


class PagedConnector(FakeConnector):
    """Una tienda de mentira que pagina como las de verdad: cada sección es una lista de páginas (de
    productos, o una excepción en la página que falla). Hace lo que pide crawl.py."""

    def __init__(self, photo, **by_section):
        super().__init__(photo)
        self.pages = by_section  # sección -> [[productos], [productos] o Exception, …]
        self.read: list[tuple[str, int]] = []

    def list_category(self, slug):
        self.calls.append(("lista", slug))
        found = []
        try:
            for number, page in enumerate(self.pages.get(slug, [[]])):
                if number >= crawl.max_pages(self.key):
                    break
                crawl.before_page()
                self.read.append((slug, number))
                if isinstance(page, Exception):
                    raise page
                found += page
                crawl.page_read(len(page))
        except ShopError as exc:
            if not found:
                raise
            raise crawl.Partial(found, exc) from exc
        return found


@pytest.fixture
def paginada(monkeypatch, photo_bytes):
    def install(**by_section) -> PagedConnector:
        connector = PagedConnector(photo_bytes, **by_section)
        monkeypatch.setitem(shops.CONNECTORS, "zara", connector)
        with SessionLocal() as db:
            shopping.set_store(db, "zara", True, None)
        return connector

    return install


def _pages(section: str, n: int, per: int = 3, type_="camisa", color="blanco", prefix=None) -> list[list]:
    prefix = prefix or section[:1]
    return [[product(f"{prefix}{p}-{i}", type_, color, section=section, name=f"Prenda {prefix}{p}x{i}")
             for i in range(per)] for p in range(n)]


def _status() -> dict:
    with SessionLocal() as db:
        return shopping.store_status(db, "zara") or {}


def _candidates() -> set[str]:
    return {i.product_ref for i in _items("candidato")}


# ---------- Recorrido completo


def test_el_recorrido_lee_todas_las_paginas_con_un_tope_de_seguridad(client, paginada, monkeypatch):
    connector = paginada(
        camisas=_pages("camisas", 5), pantalones=_pages("pantalones", 2, type_="vaquero", color="azul"),
        sudaderas=_pages("sudaderas", 70, per=1, type_="sudadera", color="gris"),
    )
    monkeypatch.setenv("ARMARIO_SHOP_MAX_PAGES_ZARA", "60")
    result = _refresh(limit=4)
    # Todas las páginas de cada sección, salvo la que pasa del tope (60 de 70).
    assert [n for s, n in connector.read if s == "camisas"] == list(range(5))
    assert sum(1 for s, _n in connector.read if s == "sudaderas") == 60
    assert result["found"] == 15 + 6 + 60 and result["added"] == 4
    status = _status()
    assert status["complete"] and status["ok_day"] == INVIERNO.isoformat() and status["cycle"] is None
    assert (status["sections"], status["sections_total"], status["pages"]) == (3, 3, 67)
    # Se recuerda cuántas páginas tuvo cada sección: la próxima vez la barra sabe el total desde el principio.
    assert status["section_pages"] == {"camisas": 5, "pantalones": 2, "sudaderas": 60}
    assert len(_candidates()) == 81 - 4  # todo guardado como candidato sin fotos, menos las 4 propuestas
    assert all(i.photos == [] for i in _items("candidato"))


def test_una_seccion_que_falla_a_mitad_no_tira_el_resto_y_se_retoma(client, paginada):
    camisas = _pages("camisas", 3)
    camisas[1] = ShopError("HTTP 500")  # la segunda página falla
    connector = paginada(camisas=camisas, pantalones=_pages("pantalones", 2, type_="vaquero", color="azul"))
    with SessionLocal() as db:
        shopping.set_store(db, "zara", True, ["camisas", "pantalones"])
    viejo = product("viejo", section="camisas")
    with SessionLocal() as db:  # un candidato de la semana pasada que la tienda ya no lista
        db.add(ShopItem(store="zara", product_ref="zara:viejo", name="Camisa vieja", price_cents=100, url="x",
                        section="camisas", type="camisa", category="parte_superior", color="blanco",
                        pattern="liso", style="casual", season="todo_el_ano", status="candidato",
                        batch=INVIERNO - timedelta(days=7), store_data=viejo.store_data))
        db.commit()

    result = _refresh(limit=0)
    assert result["ok"] and result["errors"] == ["Camisas: HTTP 500"]
    status = _status()
    # Lo leído se guarda (la primera página de Camisas y Pantalones enteros), pero no está completa.
    assert not status["complete"] and status["cycle"]["done"] == ["pantalones"] and status.get("ok_day") is None
    assert {"zara:c0-0", "zara:c0-1", "zara:p1-2"} <= _candidates()
    assert "zara:viejo" in _candidates()  # de una sección a medias no se retira nada
    with SessionLocal() as db:  # mañana por la noche toca otra vez, para retomarla
        assert shopping.due_at(db, "zara", INVIERNO) == datetime.combine(INVIERNO + timedelta(days=1),
                                                                        datetime.min.time().replace(hour=3, minute=30))

    # Al día siguiente: solo se lee la que faltaba, y ahora sí entera.
    connector.pages["camisas"] = _pages("camisas", 3)
    connector.read.clear()
    result = _refresh(INVIERNO + timedelta(days=1), limit=0)
    assert {s for s, _n in connector.read} == {"camisas"} and len(connector.read) == 3
    status = _status()
    assert status["complete"] and status["cycle"] is None and status["ok_day"] == (INVIERNO + timedelta(days=1)).isoformat()
    assert "zara:viejo" not in _candidates() and "zara:c2-2" in _candidates()
    assert "zara:p0-0" in _candidates()  # lo leído ayer sigue (es del mismo recorrido)


def test_un_bloqueo_a_mitad_guarda_lo_leido_y_al_retomar_va_mas_despacio(client, paginada):
    camisas = _pages("camisas", 3)
    camisas[2] = BlockedError("la tienda ha bloqueado el acceso (no se vuelve a intentar hasta mañana)")
    connector = paginada(camisas=camisas, pantalones=_pages("pantalones", 2, type_="vaquero", color="azul"))
    with SessionLocal() as db:
        shopping.set_store(db, "zara", True, ["camisas", "pantalones"])
    _refresh(limit=0)
    status = _status()
    assert status["blocked_day"] == INVIERNO.isoformat() and status["cycle"]["slow"]
    assert status["error"].startswith("Zara: la tienda ha bloqueado")
    assert len(_candidates()) == 6 and ("pantalones", 0) not in connector.read  # paró en seco
    with SessionLocal() as db:
        assert not shopping.reachable(db, "zara", INVIERNO)

    # Al retomar, las pausas van multiplicadas por SHOP_SLOW_FACTOR.
    connector.pages["camisas"] = _pages("camisas", 3)
    seen = []
    original = crawl.Crawl.before_page

    def spy(self):
        seen.append(self.pause)
        return original(self)

    run = crawl.Crawl("zara", pause=(0.0, 0.0))
    crawl.Crawl.before_page = spy
    try:
        with SessionLocal() as db, crawl.running(run):
            run.pause = (0.002, 0.004)
            shopping.refresh_store(db, "zara", INVIERNO + timedelta(days=1), 0, run)
    finally:
        crawl.Crawl.before_page = original
    assert seen and seen[0] == pytest.approx((0.003, 0.006))
    assert _status()["complete"]


def test_las_secciones_contenidas_en_otras_no_se_recorren(client, paginada, monkeypatch):
    connector = paginada(camisas=_pages("camisas", 2), sudaderas=_pages("sudaderas", 2, type_="sudadera"))
    monkeypatch.setattr(PagedConnector, "covered_by", {"sudaderas": ("camisas",)}, raising=False)
    with SessionLocal() as db:
        shopping.set_store(db, "zara", True, ["sudaderas", "camisas"])
    _refresh(limit=0)
    assert {s for s, _n in connector.read} == {"camisas"} and _status()["complete"]


# ---------- La hora de la noche


def test_la_consulta_toca_de_noche_en_su_dia_y_si_estaba_apagada_al_arrancar(client, paginada):
    paginada(camisas=_pages("camisas", 1))
    viernes = datetime(2026, 11, 20)
    with SessionLocal() as db:
        assert shopping.night_time(db) == "03:30"
        shopping.refresh(db, today=INVIERNO)  # «Consultar ahora» el miércoles
        assert not shopping.is_due(db, "zara", now=viernes.replace(hour=3, minute=29))
        assert shopping.is_due(db, "zara", now=viernes.replace(hour=3, minute=30))
        # Apagada el viernes por la noche: toca en cuanto arranque, el viernes a mediodía o el lunes.
        assert shopping.is_due(db, "zara", now=viernes.replace(hour=12))
        assert shopping.is_due(db, "zara", now=viernes + timedelta(days=3, hours=9))
        # Otra hora.
        shopping.set_night_time(db, "01:15")
        assert shopping.is_due(db, "zara", now=viernes.replace(hour=1, minute=15))
        assert shopping.due_at(db, "zara", viernes.date()) == viernes.replace(hour=1, minute=15)
        with pytest.raises(ValueError):
            shopping.set_night_time(db, "25:00")
    assert client.put("/api/shop/night", json={"night_time": "04:00"}).json()["night_time"] == "04:00"
    assert client.put("/api/shop/night", json={"night_time": "4h"}).status_code == 422


# ---------- Cancelar y el avance


def test_cancelar_corta_en_la_pagina_siguiente_y_guarda_lo_leido(client, paginada):
    cancel = threading.Event()
    connector = paginada(camisas=_pages("camisas", 6), pantalones=_pages("pantalones", 2, type_="vaquero"))
    original = connector.list_category

    def list_and_cancel(slug):
        if slug == "camisas":
            crawl.current().progress  # noqa: B018  (el avance existe)
            cancel.set()  # el usuario pulsa «Cancelar» mientras lee Camisas
        return original(slug)

    connector.list_category = list_and_cancel
    progress: dict = {}
    with SessionLocal() as db:
        result = shopping.refresh(db, today=INVIERNO, limit=4, cancel=cancel, progress=progress)
    assert result["cancelled"] and result["added"] == 0
    status = _status()
    assert status["cancelled"] and not status["complete"] and status["cycle"]["done"] == []
    assert connector.read == []  # ni una página: se cancela antes de pedirla
    assert progress["store"] == "zara" and progress["sections_total"] == 3


def test_el_progreso_se_estima_no_retrocede_y_calcula_lo_que_queda(monkeypatch):
    run = crawl.Crawl("zara")
    run.start_sections(3)
    run.section_start("a", "A")
    run.page_read(10)
    first = run.progress["percent"]
    assert not run.progress["known"] and run.progress["eta_seconds"] is None  # aún no se sabe el total
    run.section_total(4)  # la tienda dice que la sección tiene 4 páginas
    for _ in range(3):
        run.page_read(10)
    run.section_end()
    assert run.progress["known"]
    done, total, known = crawl.estimate(run.progress)
    # 4 leídas + 2 secciones por leer a 4 páginas + 15 fichas supuestas.
    assert (done, total, known) == (4, 4 + 8 + crawl.PROMOTE_GUESS, True)
    before = run.progress["percent"]
    assert before >= first
    # Una sección mucho más larga hace crecer el total: el porcentaje se queda donde estaba.
    run.section_start("b", "B")
    run.section_total(40)
    assert run.progress["percent"] == before
    run.progress["_t0"] -= 60  # ha pasado un minuto
    run.page_read(1)
    assert run.progress["eta_seconds"] and run.progress["eta_seconds"] > 0
    run.phase("propuestas", 10)
    for _ in range(10):
        run.step()
    assert run.progress["percent"] == 99.0  # nunca 100 hasta que acaba


# ---------- Puntuar miles de candidatos con variedad


def test_con_miles_de_candidatos_la_tanda_es_variada(client):
    rows = []
    for n in range(3000):
        kind = n % 6
        if kind < 3:  # la mitad, pantalones negros casi iguales (lo que más nota sacaría)
            rows.append(product(f"p{n}", "pantalón", "negro", name=f"Pantalon chino slim {n % 7}"))
        elif kind == 3:  # la mitad de las zapatillas, Air Force 1 en varios colores
            names = ["Air Force 1 '07", "Air Force 1 Low", "Air Force 1 '07 LV8"]
            name = names[n % 3] if n % 4 < 2 else f"Modelo {n}"
            rows.append(product(f"z{n}", "zapatillas", ["blanco", "negro", "gris"][n % 3], name=name))
        elif kind == 4:
            rows.append(product(f"c{n}", "camisa", ["blanco", "azul", "beige", "gris"][n % 4], name=f"Camisa {n}"))
        else:
            rows.append(product(f"s{n}", "sudadera", ["gris", "negro", "azul marino"][n % 3], name=f"Sudadera {n}"))
    items = []
    for row in rows:
        item = ShopItem(store="zara", product_ref=row.product_ref, name=row.name, price_cents=row.price_cents,
                        url=row.url, store_color=row.store_color, section=row.section, type=row.type,
                        category=row.category, color=row.color, pattern="liso", style="casual",
                        season="todo_el_ano", status="candidato", batch=INVIERNO, store_data={})
        item.brand = "Nike" if row.type == "zapatillas" else None
        items.append(item)

    class Plano:  # todos con la misma nota de base, salvo los pantalones negros, que sacan más
        def score(self, row):
            return (70.0 if row.type == "pantalón" else 60.0), []

    import time

    started = time.monotonic()
    ranked = shopping._ranked(Plano(), items, 40)[:40]
    assert time.monotonic() - started < 10
    picked = [row for _v, _r, row in ranked]
    types = [row.type for row in picked]
    assert types.count("pantalón") <= 15  # ni 40 pantalones negros
    models = [shopping.model_keys(row)[0] for row in picked if row.type == "zapatillas"]
    assert sum(1 for m in models if m == "nike air force") <= 2  # ni ocho Air Force 1
    assert len(set(types)) == 4


def test_las_claves_de_modelo_juntan_casi_el_mismo_nombre():
    def key(name, brand=None, color=""):
        return shopping.model_keys(product("x", name=name, color=color or "blanco") if not brand else
                                   type("R", (), {"name": name, "brand": brand, "store_color": color})())

    assert key("Air Force 1 '07", "Nike")[0] == key("Air Force 1 Low", "Nike")[0] == "nike air force"
    assert key("Boston Suede Taupe", "Birkenstock")[1] == key("Boston Birkoflor Stone", "Birkenstock")[1] == "birkenstock boston"
    assert key("Pantalon chino slim")[0] != key("Pantalon chino regular")[0]
    assert key("Pantalon chino slim")[1] == key("Pantalon chino regular")[1] == "pantalon chino"
    assert key("Chemise oxford Blanc", color="Blanc")[0] == "chemise oxford"
    assert key("X")[0] == ""


# ---------- La reserva


def test_la_reserva_se_repone_al_decidir_con_lo_guardado_y_sin_repetir_la_cola(client, tienda, monkeypatch):
    connector = tienda(camisas=[product(f"c{i}", "camisa", ["blanco", "azul", "gris", "beige"][i % 4]) for i in range(30)])
    _refresh(limit=4)
    assert len(_items("nuevo")) == 4
    for item in _items("nuevo")[:3]:
        client.post(f"/api/shop/items/{item.id}/dislike")
    connector.calls.clear()
    with SessionLocal() as db:
        assert shopping.needs_top_up(db)
        result = shopping.top_up(db, INVIERNO, target=10)
    assert result["added"] == 9 and len(_items("nuevo")) == 10
    assert connector.asked("lista") == []  # sin volver a leer el catálogo
    assert all(len(i.photos) == 2 for i in _items("nuevo"))
    # Con el bucle encendido, decidir dispara la reposición en segundo plano.
    monkeypatch.setattr(shopping.config, "SHOP_AUTO", True)
    monkeypatch.setattr(shopping.config, "SHOP_RESERVE", 12)
    monkeypatch.setattr(shopping.config, "SHOP_RESERVE_LOW", 11)
    client.post(f"/api/shop/items/{_items('nuevo')[0].id}/dislike")
    shopping.wait_idle()
    assert len(_items("nuevo")) == 12


def test_un_filtro_que_se_queda_vacio_se_repone_de_ese_tipo(client, tienda, monkeypatch):
    tienda(
        camisas=[product(f"c{i}", "camisa", "blanco") for i in range(6)],
        sudaderas=[product(f"z{i}", "chaqueta", "negro", section="sudaderas") for i in range(6)],
    )
    _refresh(limit=2)
    chaqueta = [i for i in _items("nuevo") if i.category == "capa_exterior"]
    for item in chaqueta:
        client.post(f"/api/shop/items/{item.id}/dislike")
    monkeypatch.setattr(shopping.config, "SHOP_AUTO", True)
    nxt = client.get("/api/shop/next", params={"category": "capa_exterior"}).json()
    assert nxt["item"] is None and nxt["more"] > 0
    shopping.wait_idle()
    nxt = client.get("/api/shop/next", params={"category": "capa_exterior"}).json()
    assert nxt["item"] and nxt["item"]["category"] == "capa_exterior"
    assert nxt["remaining"] == 5 and len(nxt["queue"]) == 2  # las que vienen detrás, para la pila


def test_la_reserva_de_una_tienda_de_navegador_sale_de_lo_guardado_sin_abrirlo(client, monkeypatch, tienda, photo_bytes):
    monkeypatch.setattr(browser, "missing", lambda: None)
    with SessionLocal() as db:
        shopping.set_store(db, "jdsports", True, ["baskets"])
    hits = _json("jd_listado.json")["hits"]
    session = FakeJDSession({JD_BASKETS: (200, _jd_listado(hits, pages=1))})
    _con_sesion(monkeypatch, session)
    downloaded = []
    monkeypatch.setattr(jdsports.JDSportsConnector, "download", lambda self, url: downloaded.append(url) or photo_bytes)
    _refresh(limit=1, stores=["jdsports"])
    assert session.opened == [JD_BASKETS]  # la ficha sale del listado: ni una página de producto
    monkeypatch.setattr(jdsports.browser, "require", lambda store: pytest.fail("ha abierto el navegador"))
    with SessionLocal() as db:
        shopping.top_up(db, INVIERNO, target=3)
    jd = [i for i in _items("nuevo") if i.store == "jdsports"]
    assert len(jd) == 3 and all(len(i.photos) == 3 for i in jd)
    assert all(url.startswith("https://i8.amplience.net/i/jpl/jd_") for url in downloaded)
    assert jd[0].sizes and jd[0].sizes[0]["in_stock"]


# ---------- Los colores de JD


def test_los_colores_de_jd_se_preparan_y_solo_se_ofrecen_los_preparados(client, monkeypatch, tienda, photo_bytes):
    monkeypatch.setattr(browser, "missing", lambda: None)
    with SessionLocal() as db:
        shopping.set_store(db, "jdsports", True, ["baskets"])
    hits = _json("jd_listado.json")["hits"]
    # Dos colores más del primer modelo salen también en el listado (de hombre y con talla). Cada color
    # dice cuáles son los otros, como en la tienda.
    crema = {**hits[1], "objectID": "19675025", "productRef": "725863", "name": "On Running Cloudtilt",
             "colour": "Crème"}
    bleu = {**hits[2], "objectID": "19760862", "productRef": "815629", "name": "On Running Cloudtilt",
            "colour": "Bleu"}
    family = [{"objectID": h["objectID"], "colour": h["colour"], "slug": h["slug"],
               "image": f"https://i8.amplience.net/i/jpl/jd_{h['productRef']}_plc"} for h in (hits[0], crema, bleu)]
    for extra in hits[0]["otherColourways"]:
        if extra["objectID"] not in {f["objectID"] for f in family}:
            family.append(extra)
    for hit in (hits[0], crema, bleu):
        hit["otherColourways"] = [f for f in family if f["objectID"] != hit["objectID"]]
    session = FakeJDSession({JD_BASKETS: (200, _jd_listado([hits[0], crema, bleu], pages=1))})
    _con_sesion(monkeypatch, session)
    monkeypatch.setattr(jdsports.JDSportsConnector, "download", lambda self, url: photo_bytes)
    _refresh(limit=1, stores=["jdsports"])
    item = next(i for i in _items("nuevo") if i.store == "jdsports")
    assert len(item.siblings) == 5  # él y sus cuatro colores, según el listado
    # Sin preparar, se enseñan todos, pero apagados (no se pueden ver ahora) y después del suyo.
    colors = client.post(f"/api/shop/items/{item.id}/colors").json()["colors"]
    assert len(colors) == 5 and colors[0]["current"] and colors[0]["available"]
    assert [c["available"] for c in colors[1:]] == [False] * 4 and all(c["url"] for c in colors)
    with SessionLocal() as db:
        prepared = shopping.prepare_colors(db)
    assert prepared == 2  # los dos que salieron en el listado; los otros dos, no
    colors = client.post(f"/api/shop/items/{item.id}/colors").json()["colors"]
    ready = {c["product_ref"] for c in colors if c["available"]}
    listed = {"jdsports:19772886", "jdsports:19675025", "jdsports:19760862"}
    assert item.product_ref in listed and ready == listed
    assert [c["available"] for c in colors] == [True, True, True, False, False]  # primero los disponibles
    # Elegirlo es al momento: ni navegador ni fotos nuevas.
    monkeypatch.setattr(jdsports.JDSportsConnector, "download", lambda self, url: pytest.fail("ha bajado fotos"))
    monkeypatch.setattr(jdsports.browser, "active", lambda: False)
    other = sorted(listed - {item.product_ref})[0]
    answer = client.post(f"/api/shop/items/{item.id}/color", json={"product_ref": other})
    assert answer.status_code == 200 and answer.json()["status"] == "nuevo" and len(answer.json()["photos"]) == 3
    # Los preparados que no se llegan a ver vuelven a ser candidatos con la consulta siguiente.
    session.pages[JD_BASKETS] = (200, _jd_listado([hits[0], crema, bleu], pages=1))
    _refresh(INVIERNO + timedelta(days=7), limit=0, stores=["jdsports"])
    with SessionLocal() as db:
        left = sorted(listed - {item.product_ref, other})[0]
        azul = db.scalars(select(ShopItem).where(ShopItem.product_ref == left)).one()
        assert (azul.status, azul.photos) == ("candidato", [])


# ---------- El buscador en lo guardado


def test_el_buscador_mira_primero_en_lo_guardado(client, monkeypatch, tienda, photo_bytes):
    connector = tienda(camisas=[product("ref1", "camisa", "blanco", name="Chemise oxford"),
                                product("ref2", "vaquero", "azul", name="Jean droit", section="pantalones")])
    _refresh(limit=0)
    with SessionLocal() as db:
        row = db.scalars(select(ShopItem).where(ShopItem.product_ref == "zara:ref2")).one()
        row.name_es = "Vaquero recto"
        row.store_data = {**row.store_data, "seo_id": "03918300", "model": "IF6490"}
        db.commit()
    connector.calls.clear()
    # Por palabras del nombre traducido: sin preguntar a la tienda, con su ficha y sus fotos.
    found = client.post("/api/shop/lookup", json={"query": "vaquero recto"}).json()
    assert [i["product_ref"] for i in found] == ["zara:ref2"] and found[0]["status"] == "buscado"
    assert len(found[0]["photos"]) == 2 and connector.asked("busca") == []
    # Por referencia y por código de fabricante.
    assert [i["product_ref"] for i in client.post("/api/shop/lookup", json={"query": "3918/300"}).json()] == ["zara:ref2"]
    assert [i["product_ref"] for i in client.post("/api/shop/lookup", json={"query": "if6490"}).json()] == ["zara:ref2"]
    assert connector.asked("busca") == []
    # Lo que no está guardado se pregunta a la tienda, como siempre.
    connector.found["nada guardado"] = [product("otra")]
    assert client.post("/api/shop/lookup", json={"query": "nada guardado"}).json()[0]["product_ref"] == "zara:otra"
    # Si no se guarda, el candidato vuelve al catálogo guardado (sin fotos).
    with SessionLocal() as db:
        shopping.clean_lookups(db, timedelta(0))
        row = db.scalars(select(ShopItem).where(ShopItem.product_ref == "zara:ref2")).one()
        assert (row.status, row.photos, row.last_checked_at) == ("candidato", [], None)


def test_el_buscador_encuentra_productos_de_tiendas_de_navegador(client, monkeypatch, tienda, photo_bytes):
    monkeypatch.setattr(browser, "missing", lambda: None)
    with SessionLocal() as db:
        shopping.set_store(db, "jdsports", True, ["baskets"])
    hits = _json("jd_listado.json")["hits"]
    session = FakeJDSession({JD_BASKETS: (200, _jd_listado(hits, pages=1))})
    _con_sesion(monkeypatch, session)
    monkeypatch.setattr(jdsports.JDSportsConnector, "download", lambda self, url: photo_bytes)
    _refresh(limit=0, stores=["jdsports"])
    monkeypatch.setattr(jdsports.browser, "active", lambda: False)
    # Por el enlace de JD (antes: «solo se lee con navegador») y por su referencia: con fotos de la CDN.
    link = "https://www.jdsports.fr/product/noir-on-running-cloudtilt/19772886_jdsportsfr/"
    found = client.post("/api/shop/lookup", json={"query": link}).json()
    assert [i["product_ref"] for i in found] == ["jdsports:19772886"] and len(found[0]["photos"]) == 3
    assert not found[0]["photo_pending"]
    assert client.post("/api/shop/lookup", json={"query": "807022"}).json()[0]["product_ref"] == "jdsports:19772886"
    # Uno guardado sin lo del listado (de antes): sale sin foto, y se dice que llegará.
    with SessionLocal() as db:
        row = db.scalars(select(ShopItem).where(ShopItem.product_ref == "jdsports:19713373")).one()
        row.store_data = {"id": "19713373", "slug": row.store_data["slug"], "ref": None}
        db.commit()
        name = row.name
    sin_foto = client.post("/api/shop/lookup", json={"query": name}).json()
    pending = next(i for i in sin_foto if i["product_ref"] == "jdsports:19713373")
    assert pending["photos"] == [] and pending["photo_pending"] and pending["status"] == "buscado"


# ---------- Espacio y colores


def test_el_catalogo_guardado_es_solo_texto(client, paginada):
    paginada(camisas=_pages("camisas", 10, per=20))
    _refresh(limit=0)
    with SessionLocal() as db:
        size = db.scalar(select(func.sum(func.length(ShopItem.store_data) + func.length(ShopItem.name))))
        assert db.scalar(select(func.count()).select_from(ShopItem)) == 200 and size < 200 * 300
    assert all(i.photos == [] for i in _items("candidato"))


def test_glace_es_crudo_y_el_tono_manda_sobre_una_palabra_dudosa():
    assert estimate.estimate_color("Glace") == "crudo"  # un pantalón «Glace» es beige muy claro, no celeste
    assert estimate.estimate_color("Bleu glace") == "celeste"
    # Con el tono de la tienda, una palabra dudosa no decide: el tono, sí.
    assert estimate.estimate_color("Glace", "#e8dcc8") in ("crudo", "beige")
    assert estimate.estimate_color("Glace", "#2c3e70") == "azul marino"
    assert estimate.estimate_color("Pierre", "#111111") == "negro"
    # Una palabra clara no se discute.
    assert estimate.estimate_color("Noir", "#ffffff") == "negro"
