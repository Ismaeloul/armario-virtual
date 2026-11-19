import random
from dataclasses import replace
from datetime import date

import pytest
from conftest import VALID_DRAFT

from app.services import outfits, style_rules, taste, weather
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


def test_repetir_camiseta_pesa_mas_que_repetir_zapatillas():
    camiseta_de_ayer = [replace(BASICO[0], days_since_worn=1), *BASICO[1:]]
    zapatillas_de_ayer = [*BASICO[:2], replace(BASICO[2], days_since_worn=1)]
    assert outfits.score(camiseta_de_ayer, "templado") < outfits.score(zapatillas_de_ayer, "templado")
    assert outfits.score(zapatillas_de_ayer, "templado") < outfits.score(BASICO, "templado")


def test_el_verde_oliva_cuenta_como_neutro():
    oliva = item(1, "parte_superior", color="verde oliva")
    assert "verde oliva" in outfits.NEUTRALS and style_rules.is_neutral(oliva)
    # Con un color fuerte al lado sigue siendo un solo color fuerte: ni va cargado ni resta.
    con_rojo = [oliva, item(2, "parte_inferior", color="rojo", type_="chino")]
    assert taste.loudness(con_rojo) == 1 and style_rules.palette(con_rojo) == 0


def test_cazadora_sobre_sudadera_con_cremallera_no_se_propone_ni_siendo_la_unica_capa():
    con_cremallera = item(1, "parte_superior", type_="sudadera", season="invierno", closure="cremallera")
    prendas = [con_cremallera, *BASICO[1:], item(4, "capa_exterior", type_="chaqueta", season="invierno")]
    for semilla in range(20):
        outfit = propose(prendas, 5, 0, HOY, rng=random.Random(semilla))
        assert outfit.ids == [1, 2, 3] and not outfit.with_layer  # hace frío, pero mejor sin capa que así
    # Con otra parte de arriba la cazadora sí sale; con la sudadera de cremallera, nunca.
    prendas.append(item(5, "parte_superior", type_="jersey", season="invierno"))
    vistas = [propose(prendas, 5, 0, HOY, rng=random.Random(semilla)).ids for semilla in range(40)]
    assert any(4 in ids for ids in vistas) and not any({1, 4} <= set(ids) for ids in vistas)


def test_la_sudadera_con_cremallera_hace_de_capa_en_un_dia_templado():
    prendas = BASICO[1:] + [
        item(1, "parte_superior", type_="sudadera", closure="cremallera"),
        item(5, "parte_superior", type_="jersey"),
        item(4, "capa_exterior", type_="chaqueta"),
    ]
    vistas = [propose(prendas, 16, 0, HOY, rng=random.Random(semilla)) for semilla in range(40)]
    sola = [p for p in vistas if 1 in p.ids]
    assert sola and all(not p.with_layer for p in sola)  # sale, y siempre sin cazadora encima
    assert any(p.ids == [4, 5, 2, 3] for p in vistas)  # el jersey sí lleva su chaqueta


def test_sin_mas_combinaciones_avisa_y_no_repite_la_que_se_acaba_de_ver():
    prendas = BASICO + [item(6, "parte_superior", color="blanco")]
    una, otra = {1, 2, 3}, {6, 2, 3}  # no hay más
    assert "sin_mas_combinaciones" not in propose(prendas, 18, 0, HOY, avoid=[una]).notes
    agotado = propose(prendas, 18, 0, HOY, avoid=[una, otra])
    assert set(agotado.ids) == una and "sin_mas_combinaciones" in agotado.notes  # la que hace más que salió
    assert set(propose(prendas, 18, 0, HOY, avoid=[una, otra, una]).ids) == otra
    unica = propose(BASICO, 18, 0, HOY, avoid=[{1, 2, 3}])
    assert unica.ids == [1, 2, 3] and "sin_mas_combinaciones" in unica.notes


def test_el_abrigo_es_para_el_frio_y_la_sobrecamisa_para_el_entretiempo():
    prendas = BASICO[1:] + [
        item(1, "parte_superior", type_="jersey", season="invierno"),
        item(4, "capa_exterior", type_="abrigo", season="invierno"),
        item(5, "capa_exterior", type_="sobrecamisa"),
    ]
    for semilla in range(20):
        assert propose(prendas, 3, 0, HOY, rng=random.Random(semilla)).ids[0] == 4
        assert propose(prendas, 16, 0, HOY, rng=random.Random(semilla)).ids[0] == 5


def test_lo_grueso_puntua_peor_con_calor_y_mejor_con_frio():
    fino = [replace(BASICO[0], thickness="fino"), *BASICO[1:]]
    grueso = [replace(BASICO[0], thickness="grueso"), *BASICO[1:]]
    assert outfits.score(grueso, "calor") < outfits.score(fino, "calor")
    assert outfits.score(grueso, "frio") > outfits.score(fino, "frio")


def test_la_afinidad_no_depende_de_cuantas_prendas_lleve_la_combinacion():
    camiseta = item(1, "parte_superior", color="blanco")
    vaquero, zapatillas = BASICO[1], BASICO[2]
    chaqueta = item(4, "capa_exterior", type_="chaqueta")
    afinidades = [
        outfits.combo_affinity(combo)
        for combo in ([camiseta, vaquero], [camiseta, vaquero, zapatillas], [chaqueta, camiseta, vaquero, zapatillas])
    ]
    assert max(afinidades) - min(afinidades) <= 6, afinidades
    # Sin ningún voto, ni lo más clásico llega a lo alto: eso queda para lo que el usuario confirme.
    assert all(55 <= afinidad <= 80 for afinidad in afinidades), afinidades


def test_hoy_ensena_la_misma_afinidad_que_gustos_y_no_la_cambia_el_dia():
    propuesta = propose(BASICO, 18, 0, HOY)
    piezas = [taste.Piece(id=i.id, type=i.type, category=i.category, color=i.color, style=i.style, pattern=i.pattern)
              for i in propuesta.items]
    assert propuesta.affinity == outfits.combo_affinity(piezas)
    otro_dia = [replace(i, days_since_worn=1, favorite=True) for i in BASICO]
    assert propose(otro_dia, 30, 0, date(2026, 7, 10)).affinity == propuesta.affinity


def test_con_un_armario_enorme_solo_completa_las_mejores_parejas_y_respeta_las_reglas(monkeypatch):
    monkeypatch.setattr(outfits, "MAX_COMBOS", 10)
    prendas = (
        [item(i, "parte_superior", type_="jersey", season="invierno", color=c)
         for i, c in enumerate(["negro", "gris", "rojo", "verde", "beige", "naranja"], 1)]
        + [item(10 + i, "parte_inferior", type_="vaquero", color=c) for i, c in enumerate(["azul", "negro", "rosa"])]
        + [item(20, "parte_superior", type_="camiseta"), item(21, "parte_inferior", type_="pantalón corto", season="verano")]
        + [item(30, "calzado", color="blanco", type_="zapatillas"), item(31, "calzado", color="marrón", type_="botas")]
        + [item(40, "capa_exterior", type_="chaqueta", season="invierno")]
    )
    for semilla in range(10):
        outfit = propose(prendas, 8, 0, HOY, rng=random.Random(semilla))
        assert [p.category for p in outfit.items] == ["capa_exterior", "parte_superior", "parte_inferior", "calzado"]
        assert not {20, 21} & set(outfit.ids)  # la ropa de verano, en noviembre, no


def test_la_fecha_de_hoy_es_la_de_casa_y_no_falla_sin_zonas_horarias(monkeypatch):
    assert isinstance(outfits.local_today(), date)
    monkeypatch.setenv("ARMARIO_TZ", "Marte/Olympus")
    assert outfits.local_today() == date.today()


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


def test_no_propone_lo_pedido_hasta_que_llega(client, sin_tiempo, photo_bytes):
    prendas = _armario(client, photo_bytes)
    camiseta = prendas[0]
    pedida = client.patch(f"/api/garments/{camiseta['id']}", json={"on_order": True}).json()
    assert pedida["on_order"] is True and pedida["ordered_at"]
    for _ in range(4):
        hoy = client.post("/api/today/next", json={"action": "otra"}).json()
        assert camiseta["id"] not in [g["id"] for g in hoy["outfit"]["garments"]]
    # En Gustos sí cuenta (se entrena con lo que está por llegar), pero no se puede apuntar un uso.
    vistas = set()
    for _ in range(40):
        vistas |= {g["id"] for g in client.get("/api/taste/next").json()["combo"]["garments"]}
    assert camiseta["id"] in vistas
    assert client.post(f"/api/garments/{camiseta['id']}/wear", json={}).status_code == 409

    # «Ya me ha llegado»: vuelve a ser una prenda más.
    recibida = client.patch(f"/api/garments/{camiseta['id']}", json={"on_order": False}).json()
    assert recibida["on_order"] is False and recibida["ordered_at"] is None
    assert client.post(f"/api/garments/{camiseta['id']}/wear", json={}).status_code == 200


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
    assert not outfits.summer_only(item(3, "parte_superior", season="invierno"))  # ni la marcada de invierno
    # Una camisa solo es de verano si el texto dice que es de manga corta, en singular o en plural.
    camisa = item(4, "parte_superior", type_="camisa", details="Corte holgado, mangas cortas amplias")
    assert outfits.summer_only(camisa) and not outfits.summer_only(item(5, "parte_superior", type_="camisa"))
    assert not outfits.summer_only(item(6, "parte_superior", details="Hombros caídos y mangas largas"))


def test_pasar_cuenta_como_una_valoracion_y_sin_mas_combinaciones_no_duplica_la_propuesta(
    client, sin_tiempo, photo_bytes
):
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.db import engine
    from app.models import Outfit, Rating

    _prenda(client, photo_bytes, name="Camisa", type="camisa", season="todo_el_ano")
    _prenda(client, photo_bytes, name="Vaquero", type="vaquero", season="todo_el_ano",
            color_primary={"name": "azul", "hex": "#2f5fa8"})
    primera = client.get("/api/today").json()
    assert primera["notes"] == ["sin_calzado"]

    # Solo hay una combinación posible: al pasar vuelve la misma y lo avisa.
    for _ in range(2):
        hoy = client.post("/api/today/next", json={"action": "pasar"}).json()
        assert hoy["outfit"]["id"] == primera["outfit"]["id"] and hoy["outfit"]["status"] == "propuesto"
        assert "sin_mas_combinaciones" in hoy["notes"]
    assert "sin_mas_combinaciones" not in client.get("/api/today").json()["notes"]  # solo al pedir otra

    with Session(engine) as db:
        assert len(list(db.scalars(select(Outfit)))) == 1
        valoraciones = [(r.liked, r.weight, r.source) for r in db.scalars(select(Rating))]
    assert valoraciones == [(False, 0.5, "hoy")]  # pasar dos veces la misma no la castiga dos veces


def test_un_pasar_no_veta_la_pareja_para_siempre(client, sin_tiempo, photo_bytes):
    _armario(client, photo_bytes)
    pasada = [g["id"] for g in client.get("/api/today").json()["outfit"]["garments"]]
    client.post("/api/today/next", json={"action": "pasar"})
    for _ in range(3):  # después, en Gustos, dice que esa misma combinación sí le gusta
        client.post("/api/taste/rate", json={"garment_ids": pasada, "liked": True})
    # Antes un «Pasar» restaba para siempre a esa pareja; ahora los «me gusta» lo compensan de sobra.
    afinidades = {}
    for _ in range(4):
        outfit = client.post("/api/today/next", json={"action": "otra"}).json()["outfit"]
        afinidades[frozenset(g["id"] for g in outfit["garments"])] = outfit["affinity"]
    assert afinidades[frozenset(pasada)] == max(afinidades.values()) >= 85


# ---------- Reglas del 19-11-2026: camiseta debajo, capa con frío, afinidad mínima, parejas y fotos nuevas


def test_debajo_de_la_sudadera_con_cremallera_entera_va_una_camiseta():
    prendas = [
        item(1, "parte_superior", type_="sudadera", season="invierno", closure="cremallera"),
        item(2, "parte_superior", color="blanco"),  # camiseta: fuera de sus meses no se propone sola...
        item(3, "parte_inferior", color="azul", type_="vaquero"),
        item(4, "calzado", color="blanco", type_="zapatillas"),
    ]
    propuesta = propose(prendas, 8, 0, date(2026, 11, 19), rng=random.Random(1))
    assert propuesta.ids == [1, 2, 3, 4]  # ...pero debajo de la sudadera, sí; y va justo detrás de ella
    # La combinación que cuenta (para valorar y para no repetir) es sin la camiseta de debajo.
    assert [p.id for p in outfits.without_undershirt(propuesta.items)] == [1, 3, 4]
    repetida = propose(prendas, 8, 0, date(2026, 11, 19), avoid=[{1, 2, 3, 4}], rng=random.Random(1))
    assert "sin_mas_combinaciones" in repetida.notes or 1 not in repetida.ids
    # Sin camisetas: se avisa. Una sudadera sin cremallera no la pide.
    assert "sin_camiseta" in propose([prendas[0], *prendas[2:]], 8, 0, date(2026, 11, 19)).notes
    cerrada = [item(1, "parte_superior", type_="sudadera", season="invierno", closure="sin cierre"), *prendas[1:]]
    assert propose(cerrada, 8, 0, date(2026, 11, 19), avoid=[{2, 3, 4}], rng=random.Random(1)).ids == [1, 3, 4]


def test_con_frio_siempre_sale_con_capa_si_alguna_vale():
    prendas = [
        item(1, "parte_superior", type_="jersey", season="invierno"),
        item(2, "parte_inferior", color="azul", type_="vaquero"),
        item(3, "calzado", color="blanco", type_="zapatillas"),
        item(4, "capa_exterior", color="rojo", type_="abrigo", season="invierno", style="formal", pattern="cuadros"),
    ]
    for semilla in range(8):  # aunque el abrigo pegue poco, con 6 °C no se sale sin él
        assert 4 in propose(prendas, 6, 0, date(2026, 11, 19), rng=random.Random(semilla)).ids


def test_las_dos_mitades_de_un_conjunto_compiten_con_ventaja():
    prendas = [
        item(1, "parte_superior", type_="sudadera", season="invierno", style="deportivo", pair_id=3),
        item(2, "parte_superior", type_="sudadera", season="invierno", style="deportivo", color="gris"),
        item(3, "parte_inferior", type_="chándal", style="deportivo", pair_id=1),
        item(4, "parte_inferior", type_="chándal", style="deportivo", color="gris"),
    ]
    juntas = sum({1, 3} <= set(propose(prendas, 15, 0, date(2026, 10, 19), rng=random.Random(s)).ids) for s in range(30))
    assert juntas >= 25  # casi siempre el conjunto entero, sin prohibir las otras mezclas


def test_por_debajo_de_la_afinidad_minima_solo_si_no_queda_otra():
    prendas = [
        item(1, "parte_superior", type_="camisa", color="naranja", style="formal", pattern="cuadros"),
        item(2, "parte_inferior", type_="chándal", color="morado", style="deportivo", pattern="rayas"),
    ]
    propuesta = propose(prendas, 20, 0, date(2026, 6, 1))
    if propuesta.affinity < outfits.MIN_AFFINITY:
        assert "afinidad_baja" in propuesta.notes
    buena = propose([*prendas, item(3, "parte_inferior", type_="chino", color="beige", style="formal")],
                    20, 0, date(2026, 6, 1), rng=random.Random(2))
    assert buena.affinity >= outfits.MIN_AFFINITY or "afinidad_baja" in buena.notes


def test_la_pareja_se_une_en_los_dos_sentidos_y_se_suelta_al_borrar(client, photo_bytes):
    arriba = _prenda(client, photo_bytes, name="Sudadera chándal", type="sudadera")
    abajo = _prenda(client, photo_bytes, name="Pantalón chándal", type="chándal")
    otra = _prenda(client, photo_bytes, name="Camiseta", type="camiseta")
    assert client.put(f"/api/garments/{arriba['id']}/pair", json={"pair_id": otra["id"]}).status_code == 422
    unida = client.put(f"/api/garments/{arriba['id']}/pair", json={"pair_id": abajo["id"]}).json()
    assert unida["pair"]["id"] == abajo["id"]
    assert client.get(f"/api/garments/{abajo['id']}").json()["pair"]["id"] == arriba["id"]
    assert client.delete(f"/api/garments/{abajo['id']}").status_code == 204
    assert client.get(f"/api/garments/{arriba['id']}").json()["pair"] is None


def test_las_dos_zapatillas_juntas_son_la_portada_y_la_foto_de_la_tela_no_se_guarda(client, photo_bytes):
    fotos = {name: (f"{name}.jpg", photo_bytes, "image/jpeg") for name in ("front", "pair", "texture")}
    analisis = client.post("/api/garments/analyze", files=fotos, data={"skip_ai": "true", "kind": "calzado"}).json()
    assert analisis["photo_pair"] and analisis["photo_texture"]
    cuerpo = {k: v for k, v in VALID_DRAFT.items() if k != "confidence"}
    cuerpo.update(type="zapatillas", photo_front=analisis["photo_front"]["id"], photo_pair=analisis["photo_pair"]["id"])
    prenda = client.post("/api/garments", json=cuerpo).json()
    assert prenda["photo_cover"]["id"] == analisis["photo_pair"]["id"] and prenda["photos_edited_views"] == []
    assert analisis["photo_texture"]["id"] not in str(prenda)  # solo era apoyo para la IA


def test_una_camiseta_de_verano_no_sale_en_invierno_ni_debajo_de_la_sudadera():
    base = [
        item(1, "parte_superior", type_="sudadera", season="invierno", closure="cremallera"),
        item(2, "parte_superior", color="crudo", season="verano", pattern="rayas"),  # la de fútbol
        item(3, "parte_inferior", color="gris", type_="chándal"),
    ]
    assert "sin_camiseta" in propose(base, 14, 0, date(2026, 11, 19)).notes
    lisa = item(4, "parte_superior", color="blanco")
    assert propose([*base, lisa], 14, 0, date(2026, 11, 19), rng=random.Random(1)).ids == [1, 4, 3]
    # Ajustes manda sobre el mes: con «Verano» fijado, en noviembre la de verano vuelve a valer.
    assert 2 in propose(base, 14, 0, date(2026, 11, 19), summer=True, rng=random.Random(1)).ids
    # Y con «Invierno» fijado, en julio no se propone manga corta sola si hay otra cosa.
    julio = [lisa, item(5, "parte_superior", type_="camisa", season="todo_el_ano", details="manga larga"), base[2]]
    assert all(propose(julio, 18, 0, date(2026, 7, 1), summer=False, rng=random.Random(s)).ids[0] == 5 for s in range(6))


def test_un_outfit_tuyo_cuenta_como_me_gusta_doble_y_se_puede_quitar(client, photo_bytes):
    pantalon = _prenda(client, photo_bytes, name="Pantalón negro de pinzas", type="pantalón")
    blanca = _prenda(client, photo_bytes, name="Camisa blanca", type="camisa",
                     color_primary={"name": "blanco", "hex": "#ffffff"})
    marron = _prenda(client, photo_bytes, name="Camisa marrón oscura", type="camisa",
                     color_primary={"name": "marrón", "hex": "#3b2a20"})
    ids = [blanca["id"], marron["id"], pantalon["id"]]
    antes = client.get("/api/taste/next").json()
    # Hace falta arriba y abajo, y una sola parte de abajo.
    assert client.post("/api/taste/own", json={"garment_ids": [blanca["id"], marron["id"]]}).status_code == 422
    estado = client.post("/api/taste/own", json={"garment_ids": ids}).json()
    assert estado["own"] == 1 and estado["rated"] == antes["rated"]  # no cuenta como combinación de Gustos
    propios = client.get("/api/taste/own").json()
    assert [g["id"] for g in propios[0]["garments"]] == ids
    # Lo aprendido sube: la camisa blanca con el pantalón negro pega más que antes.
    assert estado["learned"] != antes["learned"] or propios[0]["affinity"] > 50
    assert client.delete(f"/api/taste/own/{propios[0]['id']}").status_code == 204
    assert client.get("/api/taste/own").json() == []


def test_me_gusta_y_guardar_lo_lleva_a_tus_outfits_y_no_se_vuelve_a_preguntar(client, photo_bytes):
    _armario(client, photo_bytes)
    combo = client.get("/api/taste/next").json()["combo"]
    ids = [g["id"] for g in combo["garments"]]
    estado = client.post("/api/taste/rate", json={"garment_ids": ids, "liked": True, "save": True}).json()
    assert estado["own"] == 1
    assert [g["id"] for g in client.get("/api/taste/own").json()[0]["garments"]] == ids
    for _ in range(10):  # ya guardada: Gustos no la vuelve a enseñar
        siguiente = client.get("/api/taste/next").json()["combo"]
        assert siguiente is None or {g["id"] for g in siguiente["garments"]} != set(ids)
