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


def test_colores_con_una_prenda_senalada_solo_castiga_los_colores_de_esa_prenda():
    azul = pieza(5, "parte_inferior", "azul", tipo="chino")
    aprendido = taste.build(
        [Vote([VERDE, azul, ZAPA], liked=False, reasons=("colores",), culprit_ids=frozenset({VERDE.id}))] * 3
    )
    otro_azul, otra_zapa = pieza(10, "parte_inferior", "azul", tipo="chino"), pieza(11, "calzado", "blanco", tipo="zapatillas")
    assert aprendido.adjust([otro_azul, otra_zapa]) == 0  # azul con blanco no tenía la culpa
    assert aprendido.adjust([pieza(12, "parte_superior", "verde"), otro_azul]) < 0  # verde con azul, sí


def test_una_misma_cosa_no_cuenta_varias_veces_en_un_voto():
    cuatro = [pieza(1, "capa_exterior", "negro", tipo="chaqueta"), pieza(2, "parte_superior", "negro"),
              pieza(3, "parte_inferior", "negro", tipo="chino"), pieza(4, "calzado", "negro", tipo="zapatillas")]
    aprendido = taste.build([Vote(cuatro, liked=True)])
    # Seis parejas, todas «casual con casual» y «negro con negro»: es un solo voto, no seis.
    assert aprendido.seen("styles", ("casual", "casual")) == 0.5
    assert aprendido.seen("colors", ("negro", "negro")) == 0.7
    con_todo = taste.build([Vote([VERDE, ROJO], liked=False, reasons=("colores", "estilo"),
                                 culprit_ids=frozenset({VERDE.id}))])
    assert con_todo.seen("garments", (VERDE.id, ROJO.id)) == 1  # varios motivos no suman tres castigos


def test_sin_motivo_la_culpa_por_pareja_es_menor_cuantas_mas_prendas_hay():
    cuatro = [pieza(5, "capa_exterior", "gris", tipo="chaqueta"), VERDE, NEGRO, ZAPA]
    de_dos = taste.build([Vote([VERDE, NEGRO], liked=False)])
    de_cuatro = taste.build([Vote(cuatro, liked=False)])
    assert de_dos.seen("garments", (VERDE.id, NEGRO.id)) == 1 and de_cuatro.seen("garments", (VERDE.id, NEGRO.id)) == 0.5
    assert de_cuatro.adjust(cuatro) < 0  # pero la combinación entera sí queda apuntada


def test_un_pasar_baja_esa_combinacion_sin_vetar_sus_prendas_y_un_me_gusta_lo_compensa():
    pasar = Vote([VERDE, NEGRO, ZAPA], liked=False, weight=0.5)
    aprendido = taste.build([pasar])
    assert -2 < aprendido.adjust([VERDE, NEGRO, ZAPA]) < -1  # esa misma combinación, claramente menos
    otras_zapatillas = pieza(9, "calzado", "gris", tipo="zapatillas")
    assert -0.75 < aprendido.adjust([VERDE, NEGRO, otras_zapatillas]) < 0  # las mismas prendas con otra cosa, casi igual
    assert taste.build([pasar, Vote([VERDE, NEGRO, ZAPA], liked=True)]).adjust([VERDE, NEGRO, ZAPA]) > 0


def test_la_prenda_que_se_senala_una_y_otra_vez_baja_tambien_con_prendas_nuevas():
    conjuntos = [[VERDE, pieza(20 + n, "parte_inferior", "negro", tipo="chino")] for n in range(4)]
    aprendido = taste.build([Vote(c, liked=False, culprit_ids=frozenset({VERDE.id})) for c in conjuntos])
    nuevo = pieza(40, "parte_inferior", "gris", tipo="chino")
    assert aprendido.adjust([VERDE, nuevo]) < 0  # nunca se valoró con este pantalón, pero la señalada es ella
    assert aprendido.adjust([pieza(41, "parte_superior", "verde"), nuevo]) == 0  # otra prenda verde no paga por ella


def test_soso_tambien_habla_de_lo_que_va_aun_menos_cargado():
    con_un_color = [pieza(1, "parte_superior", "rojo"), pieza(2, "parte_inferior", "gris")]
    aprendido = taste.build([Vote(con_un_color, liked=False, reasons=("soso",))] * 3)
    todo_neutro = [pieza(5, "parte_superior", "blanco"), pieza(6, "parte_inferior", "beige")]
    mas_cargado = [pieza(7, "parte_superior", "verde", estampado="rayas"), pieza(8, "parte_inferior", "negro")]
    assert aprendido.adjust(todo_neutro) < 0 and aprendido.adjust(mas_cargado) == 0


def test_aprende_de_las_palabras_clave():
    def conjunto(base, capucha):
        sudadera = pieza(base + 1, "parte_superior", "gris", tipo="sudadera")
        sudadera.hood = capucha
        return [pieza(base, "capa_exterior", "negro", tipo="chaqueta"), sudadera,
                pieza(base + 2, "parte_inferior", "azul", tipo="vaquero")]

    le_gusta_con_capucha = taste.build([Vote(conjunto(10 * n, capucha=True), liked=True) for n in range(1, 5)])
    assert le_gusta_con_capucha.adjust(conjunto(100, capucha=True)) > le_gusta_con_capucha.adjust(conjunto(100, capucha=False))


def test_las_reglas_generales_ceden_ante_lo_que_el_usuario_valora():
    from app.services import style_rules

    def clasico(base):  # marino con beige: de lo más recomendado en las guías
        return [pieza(base, "parte_superior", "azul marino"), pieza(base + 1, "parte_inferior", "beige", tipo="chino")]

    def sin_regla(base):  # rosa con crudo: las guías no dicen nada
        return [pieza(base, "parte_superior", "rosa"), pieza(base + 1, "parte_inferior", "crudo", tipo="chino")]

    assert outfits.harmony(clasico(50)) > outfits.harmony(sin_regla(50))
    no_le_gusta = taste.build([Vote(clasico(10 * n), liked=False, reasons=("colores",)) for n in range(1, 5)])
    assert style_rules.prior(clasico(50), no_le_gusta.seen) < style_rules.prior(clasico(50))  # la regla pierde fuerza
    assert outfits.harmony(clasico(50), no_le_gusta) < outfits.harmony(sin_regla(50), no_le_gusta)
    assert outfits.combo_affinity(clasico(50), no_le_gusta) < 45 < outfits.combo_affinity(clasico(50))


def test_la_afinidad_de_lo_confirmado_supera_a_la_de_cualquier_cosa_sin_valorar():
    conjunto = [pieza(1, "parte_superior", "rosa"), pieza(2, "parte_inferior", "crudo", tipo="chino"), ZAPA]
    confirmado = taste.build([Vote(conjunto, liked=True)] * 3)
    assert outfits.combo_affinity(conjunto) < 80 < 90 <= outfits.combo_affinity(conjunto, confirmado)


def test_un_conjunto_que_gusta_sigue_gustando_con_una_capa_encima():
    from datetime import date

    from app.services.outfits import Item, propose

    conjunto = [pieza(1, "parte_superior", "gris", tipo="jersey"), pieza(2, "parte_inferior", "azul", tipo="vaquero"), ZAPA]
    chaqueta = pieza(5, "capa_exterior", "negro", tipo="chaqueta")
    aprendido = taste.build([Vote(conjunto, liked=True)] * 2)
    assert aprendido.adjust([chaqueta, *conjunto]) > 0.6 * aprendido.adjust(conjunto) > 0
    # Si esa combinación con chaqueta se valoró tal cual, manda esa valoración.
    con_chaqueta_no = taste.build([Vote(conjunto, liked=True)] * 2 + [Vote([chaqueta, *conjunto], liked=False)])
    assert con_chaqueta_no.adjust([chaqueta, *conjunto]) < 0 < con_chaqueta_no.adjust(conjunto)

    # Y en un día fresco Hoy lo propone con la chaqueta, no a cuerpo por ser «lo que gustó».
    prendas = [Item(id=p.id, type=p.type, category=p.category, color=p.color, style="casual", season="todo_el_ano")
               for p in [*conjunto, chaqueta]]
    import random
    for semilla in range(15):
        assert propose(prendas, 15, 0, date(2026, 11, 17), rng=random.Random(semilla), taste=aprendido).with_layer


def test_gustos_pregunta_antes_lo_que_mas_ensena():
    aprendido = taste.build([Vote([VERDE, NEGRO], liked=True)] * 2)
    assert aprendido.novelty([VERDE, NEGRO]) < aprendido.novelty([VERDE, ROJO]) <= 1


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


def test_gustos_no_pregunta_por_cazadora_sobre_sudadera_con_cremallera(client, photo_bytes):
    _prenda(client, photo_bytes, name="Sudadera", type="sudadera", closure="cremallera")
    _prenda(client, photo_bytes, name="Camisa", type="camisa", closure="botones")
    _prenda(client, photo_bytes, name="Vaquero", type="vaquero", color_primary={"name": "azul", "hex": "#2f5fa8"})
    cazadora = _prenda(client, photo_bytes, name="Cazadora", type="chaqueta")
    sudadera = client.get("/api/garments", params={"type": "sudadera"}).json()[0]

    # Dos partes de arriba, con cazadora o sin ella: 4, menos la que el usuario dijo que no se pone.
    estado = client.get("/api/taste/next").json()
    assert estado["remaining"] == 3
    vistas = []
    while estado["combo"]:
        ids = [g["id"] for g in estado["combo"]["garments"]]
        assert not {sudadera["id"], cazadora["id"]} <= set(ids) and set(ids) not in vistas
        vistas.append(set(ids))
        estado = client.post("/api/taste/rate", json={"garment_ids": ids, "liked": True}).json()
        assert estado["remaining"] == 3 - len(vistas)
    assert len(vistas) == 3


def test_gustos_con_un_armario_grande_no_repite_y_lleva_bien_la_cuenta(client, photo_bytes, monkeypatch):
    from app.routers import taste as gustos

    for n in range(4):
        _prenda(client, photo_bytes, name=f"Jersey {n}", type="jersey")
        _prenda(client, photo_bytes, name=f"Chino {n}", type="chino")
    _prenda(client, photo_bytes, name="Zapatillas", type="zapatillas")
    _prenda(client, photo_bytes, name="Abrigo", type="abrigo")
    monkeypatch.setattr(gustos, "TRIES", 5)  # para que también pase por el recorrido completo

    estado, vistas = client.get("/api/taste/next").json(), set()
    assert estado["remaining"] == 4 * 4 * 1 * 2
    while estado["combo"]:
        ids = frozenset(g["id"] for g in estado["combo"]["garments"])
        assert ids not in vistas and 1 <= estado["combo"]["affinity"] <= 99
        vistas.add(ids)
        estado = client.post("/api/taste/rate", json={"garment_ids": sorted(ids), "liked": len(vistas) % 2 == 0}).json()
        assert estado["remaining"] == 32 - len(vistas)
    assert len(vistas) == 32 and estado["rated"] == 32


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
