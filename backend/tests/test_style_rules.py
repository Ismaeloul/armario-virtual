"""Reglas generales de estilo: el punto de partida antes de aprender los gustos."""
from app.services import style_rules
from app.services.taste import Piece


def p(i, type_, category, color="negro", style="casual", pattern="liso", details=""):
    return Piece(id=i, type=type_, category=category, color=color, style=style, pattern=pattern, details=details)


def test_las_tablas_usan_solo_valores_del_catalogo():
    from app import catalog

    t = style_rules._tables()
    assert all(set(k) <= set(catalog.COLORS) for k in t["colors"])
    assert all(set(k) <= set(catalog.STYLES) for k in t["styles"])
    assert all(set(k) <= set(catalog.PATTERNS) for k in t["patterns"])
    assert all(set(k) <= set(catalog.TYPES) for k in t["types"])
    assert all(set(k) <= set(catalog.TYPES) for k in t["layers"])


def test_marino_con_beige_puntua_mejor_que_rojo_con_verde():
    clasico = [p(1, "camiseta", "parte_superior", "azul marino"), p(2, "chino", "parte_inferior", "beige")]
    choque = [p(1, "camiseta", "parte_superior", "rojo"), p(2, "chino", "parte_inferior", "verde")]
    assert style_rules.prior(clasico) > style_rules.prior(choque)


def test_cazadora_sobre_sudadera_con_cremallera_se_hunde():
    cazadora = p(1, "chaqueta", "capa_exterior")
    vaquero = p(3, "vaquero", "parte_inferior", "azul")
    con = p(2, "sudadera", "parte_superior", details="Sudadera negra con cremallera")
    sin = p(2, "sudadera", "parte_superior", details="Sudadera negra con capucha")
    assert style_rules.prior([cazadora, con, vaquero]) < style_rules.prior([cazadora, sin, vaquero]) - 3
    assert style_rules.prior([con, vaquero]) == style_rules.prior([sin, vaquero])  # sin capa, da igual


def test_chandal_con_zapatos_puntua_peor_que_con_zapatillas():
    chandal = p(1, "chándal", "parte_inferior", style="deportivo")
    top = p(2, "camiseta", "parte_superior", "blanco")
    zapatos = p(3, "zapatos", "calzado", style="formal")
    zapatillas = p(3, "zapatillas", "calzado", "blanco")
    assert style_rules.prior([top, chandal, zapatos]) < style_rules.prior([top, chandal, zapatillas])


def test_las_palabras_clave_mandan_sobre_el_texto():
    cazadora = p(1, "chaqueta", "capa_exterior")
    vaquero = p(3, "vaquero", "parte_inferior", "azul")
    media = p(2, "sudadera", "parte_superior", details="Sudadera con cremallera en el cuello")
    media.closure = "media cremallera"  # el texto dice cremallera, pero no es entera
    entera = p(2, "sudadera", "parte_superior", details="Sudadera con capucha")
    entera.closure = "cremallera"
    assert not style_rules.has_zip(media) and style_rules.has_zip(entera)
    assert style_rules.prior([cazadora, entera, vaquero]) < style_rules.prior([cazadora, media, vaquero]) - 3


def test_algo_grueso_bajo_una_cazadora_puntua_peor():
    cazadora = p(1, "chaqueta", "capa_exterior")
    vaquero = p(3, "vaquero", "parte_inferior", "azul")
    fino, gordo = p(2, "jersey", "parte_superior"), p(2, "jersey", "parte_superior")
    fino.thickness, gordo.thickness = "fino", "grueso"
    assert style_rules.prior([cazadora, gordo, vaquero]) < style_rules.prior([cazadora, fino, vaquero])
