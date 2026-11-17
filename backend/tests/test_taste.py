from conftest import VALID_DRAFT

from app.services import outfits, taste
from app.services.ai.base import build_prompt
from app.services.taste import Piece, Vote


def pieza(i, categoria, color, estilo="casual", tipo="camiseta", estampado="liso"):
    return Piece(id=i, type=tipo, category=categoria, color=color, style=estilo, pattern=estampado)


VERDE = pieza(1, "parte_superior", "verde")
NEGRO = pieza(2, "parte_inferior", "negro")
ROJO = pieza(3, "parte_inferior", "rojo")
ZAPA = pieza(4, "calzado", "blanco", tipo="zapatillas")


def test_sin_votos_no_cambia_nada():
    assert taste.build([]).adjust([VERDE, NEGRO]) == 0


def test_me_gusta_sube_y_no_me_gusta_baja():
    gusta = taste.build([Vote([VERDE, NEGRO], liked=True)] * 3)
    no_gusta = taste.build([Vote([VERDE, NEGRO], liked=False)] * 3)
    assert gusta.adjust([VERDE, NEGRO]) > 0 > no_gusta.adjust([VERDE, NEGRO])


def test_un_solo_voto_pesa_poco_y_varios_pesan_mas():
    uno = taste.build([Vote([VERDE, NEGRO], liked=True)])
    varios = taste.build([Vote([VERDE, NEGRO], liked=True)] * 5)
    assert 0 < uno.adjust([VERDE, NEGRO]) < varios.adjust([VERDE, NEGRO])


def test_el_motivo_colores_se_generaliza_a_otras_prendas_del_mismo_color():
    aprendido = taste.build([Vote([VERDE, ROJO], liked=False, reasons=("colores",))] * 3)
    otra_verde = pieza(10, "parte_superior", "verde")
    otro_rojo = pieza(11, "parte_inferior", "rojo")
    assert aprendido.adjust([otra_verde, otro_rojo]) < 0  # prendas nuevas, mismos colores
    assert aprendido.adjust([otra_verde, pieza(12, "parte_inferior", "negro")]) == 0  # verde con negro, intacto


def test_el_motivo_calzado_solo_castiga_las_parejas_con_la_zapatilla():
    aprendido = taste.build([Vote([VERDE, NEGRO, ZAPA], liked=False, reasons=("calzado",))] * 3)
    assert aprendido.adjust([VERDE, NEGRO]) == 0
    assert aprendido.adjust([VERDE, NEGRO, ZAPA]) < 0


def test_senalar_una_prenda_solo_la_castiga_a_ella():
    aprendido = taste.build([Vote([VERDE, NEGRO, ZAPA], liked=False, culprit_ids=frozenset({VERDE.id}))] * 3)
    assert aprendido.adjust([NEGRO, ZAPA]) == 0
    assert aprendido.adjust([VERDE, NEGRO]) < 0


def test_soso_y_recargado_miran_lo_cargado_del_conjunto():
    neutro = [pieza(1, "parte_superior", "negro"), pieza(2, "parte_inferior", "gris")]
    cargado = [pieza(3, "parte_superior", "rojo", estampado="gráfico"), pieza(4, "parte_inferior", "verde")]
    assert taste.loudness(neutro) == 0 and taste.loudness(cargado) == 3
    aprendido = taste.build([Vote(neutro, liked=False, reasons=("soso",))] * 3)
    otro_neutro = [pieza(5, "parte_superior", "blanco"), pieza(6, "parte_inferior", "beige")]
    assert aprendido.adjust(otro_neutro) < 0


def test_lo_aprendido_cambia_la_propuesta_del_dia():
    from datetime import date

    from app.services.outfits import Item, propose

    def item(i, categoria, color, tipo="camiseta"):
        return Item(id=i, type=tipo, category=categoria, color=color, style="casual", season="todo_el_ano")

    prendas = [item(1, "parte_superior", "blanco"), item(2, "parte_superior", "gris"),
               item(3, "parte_inferior", "negro", "pantalón")]
    odia_blanco_con_negro = taste.build(
        [Vote([pieza(1, "parte_superior", "blanco"), pieza(3, "parte_inferior", "negro")], liked=False,
              reasons=("colores",))] * 6
    )
    import random
    for semilla in range(15):
        elegido = propose(prendas, 18, 0, date(2026, 11, 17), rng=random.Random(semilla), taste=odia_blanco_con_negro)
        assert 1 not in elegido.ids


def test_la_afinidad_sube_con_los_me_gusta():
    antes = outfits.combo_affinity([VERDE, NEGRO])
    despues = outfits.combo_affinity([VERDE, NEGRO], taste.build([Vote([VERDE, NEGRO], liked=True)] * 4))
    assert despues > antes


def test_prompt_de_calzado_nombra_sus_vistas():
    texto = build_prompt(has_back=True, has_label=True, has_extra=True, kind="calzado")
    assert "4 fotos" in texto and "zapatillas o zapatos" in texto
    assert "Foto 1: el lateral" in texto and "Foto 2: la vista de frente" in texto
    assert "Foto 3: el otro lateral" in texto and "Foto 4: la etiqueta" in texto
    assert '"zapatillas", "zapatos" o "botas"' in texto
    assert "Foto 1: la parte delantera" in build_prompt(has_back=False, has_label=False)


# ---------- API


def _prenda(client, photo_bytes, **campos):
    foto = client.post("/api/garments/analyze", files={"front": ("f.jpg", photo_bytes, "image/jpeg")},
                       data={"skip_ai": "true"}).json()["photo_front"]["id"]
    cuerpo = {k: v for k, v in VALID_DRAFT.items() if k != "confidence"}
    cuerpo.update({"photo_front": foto, **campos})
    return client.post("/api/garments", json=cuerpo).json()


def test_gustos_recorre_las_combinaciones_y_aprende(client, photo_bytes):
    assert client.get("/api/taste/next").json()["combo"] is None  # sin prendas no hay nada que valorar

    _prenda(client, photo_bytes, name="Camiseta", type="camiseta")
    _prenda(client, photo_bytes, name="Camisa", type="camisa", color_primary={"name": "blanco", "hex": "#ffffff"})
    _prenda(client, photo_bytes, name="Vaquero", type="vaquero", color_primary={"name": "azul", "hex": "#2f5fa8"})

    estado = client.get("/api/taste/next").json()
    assert estado["remaining"] == 2 and estado["rated"] == 0
    ids = [g["id"] for g in estado["combo"]["garments"]]

    estado = client.post("/api/taste/rate", json={"garment_ids": ids, "liked": False,
                                                  "reasons": ["colores", "soso"], "culprit_ids": ids[:2]}).json()
    assert (estado["rated"], estado["liked"], estado["remaining"]) == (1, 0, 1)
    otros = [g["id"] for g in estado["combo"]["garments"]]
    assert set(otros) != set(ids)  # no repite la ya valorada

    estado = client.post("/api/taste/rate", json={"garment_ids": otros, "liked": True}).json()
    assert estado["combo"] is None and (estado["rated"], estado["liked"]) == (2, 1)

    assert client.post("/api/taste/rate", json={"garment_ids": [ids[0], 999], "liked": True}).status_code == 404
    assert client.post("/api/taste/rate", json={"garment_ids": ids, "liked": False, "reasons": ["feo"]}).status_code == 422

    assert client.delete("/api/taste").status_code == 204
    assert client.get("/api/taste/next").json()["rated"] == 0


def test_zapatilla_con_tres_vistas(client, analyzers, photo_bytes):
    import json

    from conftest import FakeAnalyzer

    borrador = {**VALID_DRAFT, "name": "Zapatilla gris", "type": "zapatillas"}
    codex, _ = analyzers(FakeAnalyzer("codex", json.dumps(borrador)), FakeAnalyzer("claude"))
    foto = ("z.jpg", photo_bytes, "image/jpeg")
    analisis = client.post("/api/garments/analyze", files={"front": foto, "back": foto, "extra": foto},
                           data={"kind": "calzado"}).json()
    assert analisis["photo_extra"] and len(codex.images) == 3
    assert "Foto 3: el otro lateral" in codex.prompt

    cuerpo = {k: v for k, v in analisis["draft"].items() if k not in ("confidence", "color_primary_alt")}
    cuerpo.update(photo_front=analisis["photo_front"]["id"], photo_back=analisis["photo_back"]["id"],
                  photo_extra=analisis["photo_extra"]["id"])
    prenda = client.post("/api/garments", json=cuerpo).json()
    assert prenda["category"] == "calzado" and prenda["photo_extra"]["id"] == analisis["photo_extra"]["id"]


def test_se_pueden_senalar_varias_prendas():
    aprendido = taste.build([Vote([VERDE, NEGRO, ZAPA], liked=False, culprit_ids=frozenset({VERDE.id, ZAPA.id}))] * 3)
    assert aprendido.adjust([VERDE, NEGRO]) < 0 and aprendido.adjust([NEGRO, ZAPA]) < 0  # las dos señaladas
    assert aprendido.adjust([NEGRO, pieza(9, "calzado", "gris")]) == 0  # lo no señalado, intacto
