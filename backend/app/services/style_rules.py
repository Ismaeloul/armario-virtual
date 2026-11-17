"""Punto de partida del algoritmo: reglas generales de estilo, antes de conocer los gustos del usuario.

`style_rules.json` sale de una búsqueda por guías de moda masculina (ver sus "fuentes"): parejas de
colores, de estilos, de estampados y de tipos de prenda, y qué capa va sobre qué parte de arriba,
cada una con una nota de -2 (choca) a 2 (clásico). Aquí solo se suman, con poco peso, para que lo
que el usuario valore en Gustos (services/taste.py) acabe pesando más que lo que dice internet.
"""
import itertools
import json
from functools import lru_cache
from pathlib import Path

_FILE = Path(__file__).with_name("style_rules.json")

# Cuánto cuenta cada tabla por pareja de prendas.
W_COLOR, W_STYLE, W_PATTERN, W_TYPE, W_LAYER = 0.4, 0.3, 0.3, 0.5, 0.6
# Regla del usuario: una cazadora o sobrecamisa encima de una sudadera con cremallera no se pone.
ZIP_CLASH = -10.0


@lru_cache(maxsize=1)
def _tables() -> dict:
    raw = json.loads(_FILE.read_text(encoding="utf-8"))

    def pairs(section: str) -> dict:
        return {frozenset((row["a"], row["b"])): float(row["score"]) for row in raw.get(section, [])}

    return {
        "colors": pairs("color_pairs"),
        "styles": pairs("style_pairs"),
        "patterns": pairs("pattern_pairs"),
        "types": pairs("type_pairs"),
        "layers": {(row["capa"], row["arriba"]): float(row["score"]) for row in raw.get("layer_over_top", [])},
    }


def _denim_blue(piece) -> bool:
    return piece.type == "vaquero" and piece.color in {"azul", "celeste"}  # el vaquero azul va con todo


def has_zip(piece) -> bool:
    return "cremallera" in (getattr(piece, "details", "") or "").lower()


def prior(pieces: list) -> float:
    """Cuánto sube o baja una combinación según las reglas generales. Sirve para Item y para Piece."""
    t = _tables()
    total = 0.0
    for a, b in itertools.combinations(pieces, 2):
        if not (_denim_blue(a) or _denim_blue(b)):
            total += W_COLOR * t["colors"].get(frozenset((a.color, b.color)), 0.0)
        total += W_STYLE * t["styles"].get(frozenset((a.style, b.style)), 0.0)
        total += W_PATTERN * t["patterns"].get(frozenset((a.pattern, b.pattern)), 0.0)
        total += W_TYPE * t["types"].get(frozenset((a.type, b.type)), 0.0)

    layer = next((p for p in pieces if p.category == "capa_exterior"), None)
    top = next((p for p in pieces if p.category == "parte_superior"), None)
    if layer and top:
        total += W_LAYER * t["layers"].get((layer.type, top.type), 0.0)
        if top.type == "sudadera" and has_zip(top) and layer.type in ("chaqueta", "sobrecamisa"):
            total += ZIP_CLASH
    return total
