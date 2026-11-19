"""Simulación del algoritmo entero: un armario inventado y un usuario inventado con un gusto fijo.

Comprueba lo que no se ve en las pruebas pequeñas: que después de unas cuantas valoraciones en Gustos
las propuestas de Hoy se mueven hacia ese gusto (aunque vaya contra las reglas generales), que la
afinidad separa lo que le gusta de lo que no, y que las reglas del usuario se cumplen siempre.
Todo el azar lleva semilla: el resultado es el mismo en cada ejecución.
"""
import copy
import random
from datetime import date, timedelta
from statistics import mean

from app import catalog
from app.services import outfits, style_rules, taste
from app.services.outfits import Item, propose
from app.services.taste import Piece, Vote


def prenda(i, tipo, color, estilo="casual", temporada="todo_el_ano", estampado="liso", **claves):
    return Item(id=i, type=tipo, category=catalog.TYPES[tipo], color=color, style=estilo, season=temporada,
                pattern=estampado, **claves)


ARMARIO = [
    # Parte superior
    prenda(1, "camiseta", "blanco"), prenda(2, "camiseta", "negro"),
    prenda(3, "camiseta", "rojo", estampado="gráfico"), prenda(4, "camiseta", "verde"),
    prenda(5, "camisa", "celeste", "smart casual"), prenda(6, "camisa", "blanco", "formal"),
    prenda(7, "polo", "azul marino", "smart casual"),
    prenda(8, "sudadera", "gris", temporada="invierno", closure="sin cierre", hood=True, thickness="grueso"),
    prenda(9, "sudadera", "negro", temporada="invierno", closure="cremallera", hood=True, thickness="medio"),
    prenda(10, "sudadera", "naranja", "deportivo", "invierno", "logo"),
    prenda(11, "jersey", "beige", "smart casual", "invierno", thickness="fino"),
    prenda(12, "jersey", "burdeos", temporada="invierno", thickness="grueso"),
    prenda(13, "camisa", "azul marino", details="Camisa de manga larga"),
    prenda(14, "sudadera", "verde", temporada="invierno"),
    # Parte inferior
    prenda(20, "vaquero", "azul"), prenda(21, "vaquero", "negro"), prenda(22, "chino", "beige", "smart casual"),
    prenda(23, "pantalón", "gris", "formal"), prenda(24, "chándal", "gris", "deportivo"),
    prenda(25, "pantalón corto", "azul marino", temporada="verano"), prenda(26, "chino", "verde oliva"),
    prenda(27, "vaquero", "celeste"),
    # Calzado
    prenda(30, "zapatillas", "blanco"), prenda(31, "zapatillas", "negro", "deportivo"),
    prenda(32, "zapatos", "marrón", "formal"), prenda(33, "botas", "marrón", temporada="invierno"),
    # Capa exterior
    prenda(40, "chaqueta", "negro", temporada="invierno"), prenda(41, "sobrecamisa", "verde oliva"),
    prenda(42, "abrigo", "gris", "smart casual", "invierno"), prenda(43, "chaqueta", "rojo", "deportivo"),
]
POR_CATEGORIA: dict[str, list[Item]] = {}
for _prenda in ARMARIO:
    POR_CATEGORIA.setdefault(_prenda.category, []).append(_prenda)

# (fecha, máxima, % de lluvia): invierno, entretiempo con lluvia, verano y un día suelto de calor en febrero.
DIAS = [
    (date(2026, 11, 17), 8, 0), (date(2026, 1, 10), 3, 20), (date(2026, 4, 12), 16, 70),
    (date(2026, 7, 10), 30, 0), (date(2026, 6, 2), 21, 0), (date(2026, 2, 20), 24, 0),
]


def pieza(p: Item) -> Piece:
    return Piece(id=p.id, type=p.type, category=p.category, color=p.color, style=p.style, pattern=p.pattern,
                 details=p.details, closure=p.closure, fit=p.fit, thickness=p.thickness, hood=p.hood)


def de(combo, categoria):
    return next((p for p in combo if p.category == categoria), None)


# ---------- Dos usuarios inventados: (le gusta, motivos, prendas que señala)


def neutros_con_vaquero(combo):
    """Le gustan los neutros con vaquero; no le gusta mezclar deportivo con formal ni los colores fuertes."""
    fuertes = frozenset(p.id for p in combo if not style_rules.is_neutral(p))
    if {"deportivo", "formal"} <= {p.style for p in combo}:
        return False, ("estilo",), frozenset()
    if fuertes:
        return False, ("colores",), fuertes
    if de(combo, "parte_inferior").type != "vaquero":
        return False, (), frozenset({de(combo, "parte_inferior").id})
    return True, (), frozenset()


def deportivo_con_formal(combo):
    """Al revés que las guías: solo le gusta cuando se mezclan lo deportivo y lo formal."""
    if {"deportivo", "formal"} <= {p.style for p in combo}:
        return True, (), frozenset()
    return False, ("estilo",), frozenset()


# ---------- La simulación


def combinacion_al_azar(rng):
    """Como las que pregunta Gustos: sin mezclar verano con invierno y sin lo que nunca se pone."""
    while True:
        capa = rng.choice([None, *POR_CATEGORIA["capa_exterior"]])
        arriba = rng.choice(POR_CATEGORIA["parte_superior"])
        combo = [p for p in (capa, arriba, rng.choice(POR_CATEGORIA["parte_inferior"]),
                             rng.choice(POR_CATEGORIA["calzado"])) if p is not None]
        if capa is not None and style_rules.zip_clash(capa, arriba):
            continue
        if not {"verano", "invierno"} <= {p.season for p in combo}:
            return combo


def valorar(usuario, votos, semilla=0, despiste=0.0):
    """Lo aprendido tras valorar `votos` combinaciones al azar. Con `despiste`, a veces vota al revés y sin motivo."""
    rng = random.Random(semilla)
    resultado = []
    for _ in range(votos):
        combo = combinacion_al_azar(rng)
        gusta, motivos, senaladas = usuario(combo)
        if rng.random() < despiste:
            gusta, motivos, senaladas = not gusta, (), frozenset()
        resultado.append(Vote([pieza(p) for p in combo], gusta, 1.0, motivos, senaladas))
    return taste.build(resultado)


def propuestas(aprendido, semillas=10):
    return [
        (dia, maxima, propose(ARMARIO, maxima, lluvia, dia, rng=random.Random(semilla), taste=aprendido))
        for dia, maxima, lluvia in DIAS
        for semilla in range(semillas)
    ]


def acierto(usuario, aprendido) -> float:
    """Qué parte de las propuestas de Hoy le gustaría a ese usuario."""
    todas = propuestas(aprendido)
    return sum(usuario(propuesta.items)[0] for _, _, propuesta in todas) / len(todas)


def comprobar_reglas(dia, maxima, propuesta):
    # La camiseta que va debajo de la sudadera con cremallera es un añadido: las reglas miran lo demás.
    combo = outfits.without_undershirt(propuesta.items)
    arriba, capa = de(combo, "parte_superior"), de(combo, "capa_exterior")
    if outfits.needs_undershirt(arriba) and "sin_camiseta" not in propuesta.notes:
        assert [p.type for p in propuesta.items].count("camiseta") == 1, propuesta.ids
    assert [p.category for p in combo if p.category != "capa_exterior"] == ["parte_superior", "parte_inferior", "calzado"]
    assert len(combo) == len({p.category for p in combo})  # una prenda por hueco
    # Cazadora o sobrecamisa sobre sudadera con cremallera entera: nunca.
    assert not (capa and style_rules.zip_clash(capa, arriba)), propuesta.ids
    # Ropa de verano (pantalón corto, manga corta), solo del 1 de mayo al 30 de septiembre.
    if not 5 <= dia.month <= 9:
        assert not any(p.type == "pantalón corto" or p.season == "verano" for p in combo), propuesta.ids
        assert not any(p.type in ("camiseta", "polo") for p in combo), propuesta.ids
    # Con calor, ni capa ni ropa de invierno si hay alternativa (en febrero no la hay: lo de verano no vale).
    if propuesta.day_kind == "calor":
        assert capa is None
        if 5 <= dia.month <= 9:
            assert not any(p.season == "invierno" for p in combo), propuesta.ids
    if propuesta.day_kind == "frio":
        assert not any(p.season == "verano" for p in combo), propuesta.ids
    # El abrigo, para el frío; con 14 °C o más sobra.
    if capa is not None and maxima >= outfits.COAT_TOO_WARM_FROM:
        assert capa.type != "abrigo", propuesta.ids
    assert 1 <= propuesta.affinity <= 99


def test_tras_valorar_las_propuestas_se_acercan_al_gusto_del_usuario():
    al_azar = mean(neutros_con_vaquero(combinacion_al_azar(random.Random(n)))[0] for n in range(1000))
    sin_votos = acierto(neutros_con_vaquero, None)
    con_20 = acierto(neutros_con_vaquero, valorar(neutros_con_vaquero, 20))
    con_60 = acierto(neutros_con_vaquero, valorar(neutros_con_vaquero, 60))
    assert al_azar < 0.25  # es un gusto exigente: le vale menos de una de cada cuatro combinaciones
    assert sin_votos < 0.5  # las reglas generales solas no lo adivinan
    assert con_20 > sin_votos + 0.3  # con 20 valoraciones ya se nota
    assert con_60 >= 0.9  # y con 60 casi todo lo que se propone le gusta


def test_aprende_aunque_el_usuario_se_equivoque_a_veces():
    despistado = valorar(neutros_con_vaquero, 80, semilla=1, despiste=0.15)  # 1 de cada 7 votos, al revés
    assert acierto(neutros_con_vaquero, despistado) >= 0.75


def test_un_gusto_contrario_a_las_reglas_generales_acaba_mandando():
    assert acierto(deportivo_con_formal, None) < 0.1  # las guías dicen que no se mezclan
    assert acierto(deportivo_con_formal, valorar(deportivo_con_formal, 120)) >= 0.6


def test_la_afinidad_separa_lo_que_le_gusta_de_lo_que_no():
    muestra = [combinacion_al_azar(random.Random(1000 + n)) for n in range(400)]
    aprendido = valorar(neutros_con_vaquero, 60)

    def medias(gusto):
        si = [outfits.combo_affinity(c, gusto) for c in muestra if neutros_con_vaquero(c)[0]]
        no = [outfits.combo_affinity(c, gusto) for c in muestra if not neutros_con_vaquero(c)[0]]
        return mean(si), mean(no)

    antes, despues = medias(None), medias(aprendido)
    assert antes[0] - antes[1] < 15  # sin votos apenas las distingue
    assert despues[0] >= 80 and despues[0] - despues[1] >= 35, despues
    # La afinidad no premia llevar más prendas: de media, con capa o sin ella sale parecido.
    por_tamano = {n: mean(outfits.combo_affinity(c) for c in muestra if len(c) == n) for n in (3, 4)}
    assert abs(por_tamano[3] - por_tamano[4]) < 8, por_tamano


def test_las_reglas_del_usuario_se_cumplen_con_y_sin_valoraciones():
    for aprendido in (None, valorar(neutros_con_vaquero, 60), valorar(deportivo_con_formal, 120)):
        for dia, maxima, propuesta in propuestas(aprendido, semillas=6):
            comprobar_reglas(dia, maxima, propuesta)


def test_dos_semanas_seguidas_no_repite_combinacion_ni_propone_lo_de_la_lavadora():
    aprendido = valorar(neutros_con_vaquero, 60)
    prendas = copy.deepcopy(ARMARIO)
    rng = random.Random(3)
    ultimo_uso: dict[int, int] = {}
    elegidos: list[set[int]] = []
    lavadora: set[int] = set()
    inicio = date(2026, 11, 2)
    for n, maxima in enumerate([8, 9, 6, 11, 12, 7, 5, 9, 10, 8, 4, 6, 9, 12]):
        for p in prendas:
            p.days_since_worn = n - ultimo_uso[p.id] if p.id in ultimo_uso else None
        disponibles = [p for p in prendas if p.id not in lavadora]
        propuesta = propose(disponibles, maxima, 0, inicio + timedelta(days=n), avoid=elegidos[-7:], rng=rng,
                            taste=aprendido)
        comprobar_reglas(inicio + timedelta(days=n), maxima, propuesta)
        assert set(propuesta.ids) not in elegidos[-7:] and not set(propuesta.ids) & lavadora
        assert "sin_mas_combinaciones" not in propuesta.notes
        if n:  # la parte de arriba de ayer no se repite hoy
            assert de(propuesta.items, "parte_superior").id != arriba_de_ayer
        arriba_de_ayer = de(propuesta.items, "parte_superior").id
        elegidos.append(set(propuesta.ids))  # «Me gusta»: se lo pone
        ultimo_uso.update(dict.fromkeys(propuesta.ids, n))
        lavadora = {arriba_de_ayer} if n % 2 else lavadora | {arriba_de_ayer}  # y la parte de arriba, a lavar
    assert len({frozenset(ids) for ids in elegidos}) >= 10  # pasada una semana, una que gustó puede volver
    assert mean(neutros_con_vaquero([p for p in ARMARIO if p.id in ids])[0] for ids in elegidos) >= 0.7
