import random
from datetime import date

import pytest
from conftest import VALID_DRAFT

from app.services import outfits, weather
from app.services.outfits import Item, day_kind, propose

HOY = date(2026, 11, 17)


def item(i, category, color="negro", season="todo_el_ano", type_="camiseta", style="casual", **kw):
    return Item(id=i, type=type_, category=category, color=color, style=style, season=season, **kw)


BASICO = [
    item(1, "parte_superior"),
    item(2, "parte_inferior", color="azul", type_="vaquero"),
    item(3, "calzado", color="blanco", type_="zapatillas"),
]


def test_tipo_de_dia_segun_la_temperatura_o_el_mes():
    assert day_kind(28, HOY) == "calor"
    assert day_kind(8, HOY) == "frio"
    assert day_kind(18, HOY) == "templado"
    assert day_kind(None, date(2026, 7, 1)) == "calor"
    assert day_kind(None, date(2026, 1, 10)) == "frio"


def test_hace_falta_parte_superior_e_inferior():
    assert propose([item(1, "parte_superior")], 18, 0, HOY) is None
    assert propose(BASICO, 18, 0, HOY).ids == [1, 2, 3]


def test_sin_calzado_propone_igual_y_lo_avisa():
    outfit = propose(BASICO[:2], 18, 0, HOY)
    assert outfit.ids == [1, 2] and "sin_calzado" in outfit.notes


def test_con_frio_anade_capa_exterior_y_con_calor_no():
    prendas = BASICO + [item(4, "capa_exterior", type_="chaqueta", season="invierno")]
    assert propose(prendas, 8, 0, HOY).ids[0] == 4
    assert 4 not in propose(prendas, 28, 0, HOY).ids
    assert "sin_capa" in propose(BASICO, 8, 0, HOY).notes


def test_con_calor_no_elige_prendas_de_invierno_si_hay_alternativa():
    prendas = BASICO + [item(5, "parte_superior", season="invierno", type_="sudadera")]
    for seed in range(20):
        assert 5 not in propose(prendas, 30, 0, date(2026, 7, 10), rng=random.Random(seed)).ids


def test_no_repite_una_combinacion_ya_propuesta():
    prendas = BASICO + [item(6, "parte_superior", color="blanco")]
    primera = propose(prendas, 18, 0, HOY, rng=random.Random(1))
    segunda = propose(prendas, 18, 0, HOY, avoid=[set(primera.ids)], rng=random.Random(1))
    assert set(segunda.ids) != set(primera.ids)


def test_evita_juntar_varios_colores_fuertes():
    neutro = [item(1, "parte_superior", color="rojo"), item(2, "parte_inferior", color="negro")]
    chillon = [item(1, "parte_superior", color="rojo"), item(2, "parte_inferior", color="verde")]
    assert outfits.score(neutro, "templado") > outfits.score(chillon, "templado")


def test_lo_usado_ayer_puntua_peor():
    fresco = [item(1, "parte_superior"), item(2, "parte_inferior")]
    repetido = [item(1, "parte_superior", days_since_worn=1), item(2, "parte_inferior")]
    assert outfits.score(fresco, "templado") > outfits.score(repetido, "templado")


def test_lee_la_prevision_de_open_meteo():
    w = weather.parse_forecast("Argenteuil", {
        "current": {"temperature_2m": 9.4, "weather_code": 3},
        "daily": {"temperature_2m_max": [11.6], "temperature_2m_min": [5.2],
                  "precipitation_probability_max": [70], "weather_code": [61]},
    })
    assert (w.temp_now, w.temp_max, w.temp_min, w.rain_probability) == (9, 12, 5, 70)
    assert w.description == "Lluvia débil" and w.icon == "rain"


# ---------- API


@pytest.fixture
def sin_tiempo(monkeypatch):
    """Sin red en los tests: el tiempo se fija a mano."""
    def fijar(temp_max=18, lluvia=0):
        w = None if temp_max is None else weather.Weather("Argenteuil", temp_max - 2, temp_max, temp_max - 8, lluvia, "Nublado", "cloud")
        monkeypatch.setattr(weather, "today", lambda city: w)
    fijar()
    return fijar


def _prenda(client, photo_bytes, **campos):
    foto = client.post("/api/garments/analyze", files={"front": ("f.jpg", photo_bytes, "image/jpeg")},
                       data={"skip_ai": "true"}).json()["photo_front"]["id"]
    cuerpo = {k: v for k, v in VALID_DRAFT.items() if k != "confidence"}
    cuerpo.update({"photo_front": foto, **campos})
    respuesta = client.post("/api/garments", json=cuerpo)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def _armario(client, photo_bytes):
    return [
        _prenda(client, photo_bytes, name="Camiseta", type="camiseta", season="todo_el_ano"),
        _prenda(client, photo_bytes, name="Camisa", type="camisa", season="todo_el_ano",
                color_primary={"name": "blanco", "hex": "#ffffff"}),
        _prenda(client, photo_bytes, name="Vaquero", type="vaquero", season="todo_el_ano",
                color_primary={"name": "azul", "hex": "#2f5fa8"}),
        _prenda(client, photo_bytes, name="Zapatillas", type="zapatillas", season="todo_el_ano",
                color_primary={"name": "blanco", "hex": "#ffffff"}),
    ]


def test_armario_incompleto_dice_que_falta(client, sin_tiempo, photo_bytes):
    hoy = client.get("/api/today").json()
    assert hoy["outfit"] is None and hoy["missing"] == ["Parte superior", "Parte inferior"]
    _prenda(client, photo_bytes, type="camiseta")
    assert client.get("/api/today").json()["missing"] == ["Parte inferior"]


def test_propone_un_outfit_y_lo_mantiene_al_recargar(client, sin_tiempo, photo_bytes):
    _armario(client, photo_bytes)
    hoy = client.get("/api/today").json()
    assert hoy["weather"]["temp_max"] == 18 and hoy["city"] == "Argenteuil"
    categorias = [g["category"] for g in hoy["outfit"]["garments"]]
    assert categorias == ["parte_superior", "parte_inferior", "calzado"]
    assert client.get("/api/today").json()["outfit"]["id"] == hoy["outfit"]["id"]


def test_generar_otra_cambia_la_propuesta(client, sin_tiempo, photo_bytes):
    _armario(client, photo_bytes)
    primera = client.get("/api/today").json()["outfit"]
    segunda = client.post("/api/today/next", json={"action": "otra"}).json()["outfit"]
    assert segunda["id"] != primera["id"]
    assert {g["id"] for g in segunda["garments"]} != {g["id"] for g in primera["garments"]}


def test_me_gusta_apunta_el_uso_y_se_puede_deshacer(client, sin_tiempo, photo_bytes):
    _armario(client, photo_bytes)
    elegido = client.post("/api/today/choose").json()["outfit"]
    assert elegido["status"] == "elegido"
    assert all(g["wear_count"] == 1 for g in elegido["garments"])
    assert client.post("/api/today/next", json={"action": "otra"}).status_code == 409  # ya elegido

    deshecho = client.post("/api/today/unchoose").json()["outfit"]
    assert deshecho["status"] == "propuesto" and all(g["wear_count"] == 0 for g in deshecho["garments"])


def test_no_propone_lo_que_esta_en_la_lavadora(client, sin_tiempo, photo_bytes):
    prendas = _armario(client, photo_bytes)
    camiseta, camisa = prendas[0], prendas[1]
    client.patch(f"/api/garments/{camiseta['id']}", json={"in_laundry": True})
    for _ in range(4):
        hoy = client.post("/api/today/next", json={"action": "otra"}).json()
        assert camiseta["id"] not in [g["id"] for g in hoy["outfit"]["garments"]]
    assert hoy["in_laundry"] == 1

    # Si la prenda de la propuesta actual se mete en la lavadora, se propone otra cosa.
    client.patch(f"/api/garments/{camiseta['id']}", json={"in_laundry": False})
    client.patch(f"/api/garments/{camisa['id']}", json={"in_laundry": True})
    assert camisa["id"] not in [g["id"] for g in client.get("/api/today").json()["outfit"]["garments"]]


def test_sin_dato_del_tiempo_propone_igual(client, sin_tiempo, photo_bytes):
    sin_tiempo(None)
    _armario(client, photo_bytes)
    hoy = client.get("/api/today").json()
    assert hoy["weather"] is None and hoy["outfit"] is not None


def test_fuera_de_los_meses_de_calor_no_propone_ropa_de_verano_aunque_suba_la_temperatura():
    prendas = [
        item(1, "parte_superior", type_="camiseta"),
        item(2, "parte_superior", type_="sudadera", season="invierno"),
        item(3, "parte_inferior", type_="pantalón corto", season="verano"),
        item(4, "parte_inferior", color="azul", type_="vaquero"),
        item(5, "calzado", color="blanco", type_="zapatillas"),
    ]
    for semilla in range(20):
        invierno = propose(prendas, 24, 0, date(2026, 2, 20), rng=random.Random(semilla))
        assert {p.id for p in invierno.items} == {2, 4, 5}
    verano = propose(prendas, 30, 0, date(2026, 7, 10), rng=random.Random(1))
    assert 2 not in {p.id for p in verano.items}


def test_la_camiseta_de_manga_larga_no_cuenta_como_de_verano():
    larga = item(1, "parte_superior", details="Camiseta manga larga")
    assert outfits.summer_only(item(2, "parte_superior")) and not outfits.summer_only(larga)
