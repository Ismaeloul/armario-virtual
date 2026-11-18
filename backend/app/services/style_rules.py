"""Punto de partida del algoritmo: reglas generales de estilo, antes de conocer los gustos del usuario.

`style_rules.json` sale de una búsqueda por guías de moda masculina (ver sus "fuentes"): parejas de
colores, de estilos, de estampados y de tipos de prenda, y qué capa va sobre qué parte de arriba,
cada una con una nota de -2 (choca) a 2 (clásico).

Aquí se convierten en una sola nota por combinación (`prior`). Dos ideas la gobiernan:

  · Se hace la media por pareja, no la suma: así cuatro prendas no puntúan más que dos solo por
    tener más parejas, y la nota se puede comparar entre combinaciones de 2, 3 y 4 prendas.
  · Son solo el punto de partida. Cada regla pierde fuerza según el usuario va valorando justo eso
    en Gustos (`seen`): con el tiempo manda lo que él opina (services/taste.py), no lo que dice internet.

También vive aquí el vocabulario que comparten las reglas y lo aprendido (qué es un color neutro,
qué parejas se miran, qué rasgos salen de las palabras clave), para que no se desajusten.
"""
import itertools
import json
from functools import lru_cache
from pathlib import Path

_FILE = Path(__file__).with_name("style_rules.json")

# La base neutra de style_rules.json: colores que combinan con casi todo.
NEUTRALS = frozenset({"negro", "blanco", "gris", "beige", "crudo", "azul marino", "marrón", "verde oliva"})
# El vaquero azul o celeste es un tono aparte que va con todo: ni choca ni compite con otros azules.
DENIM = "vaquero"
DENIM_SCORE = 1.0  # su nota con cualquier color, en la escala de las tablas

# Cuánto cuenta cada tabla (sus notas van de -2 a 2).
W_COLOR, W_STYLE, W_PATTERN, W_TYPE = 0.4, 0.4, 0.25, 0.5
# Ir del mismo registro es lo normal, no un mérito: los estilos se miden respecto a esa nota.
SAME_REGISTER = 2.0
# Más de un color fuerte a la vez (regla "uno o dos colores vivos, en toques pequeños"), por cada color de más.
CROWDED_PALETTE = -1.0
# Una pareja que choca pesa más que la media: el conjunto es tan bueno como su peor pareja.
WEAKEST_LINK = 0.5
# Votos sobre una misma cosa con los que su regla general pasa a contar la mitad.
TRUST_HALF = 3.0

# Regla del usuario: una cazadora o sobrecamisa encima de una sudadera con cremallera entera no se pone.
# No se desgasta con los votos, y al proponer el outfit del día esas combinaciones ni se consideran.
ZIP_CLASH = -10.0
# Bajo una cazadora o una sobrecamisa no cabe bien algo gordo, ni algo ancho si la capa es ajustada;
# y dos capuchas, una encima de otra, abultan. En la escala de las tablas.
BULKY_UNDER_LAYER = -3.0
DOUBLE_HOOD = -2.0

# Las parejas donde importa el tipo de prenda: arriba con abajo, abajo con calzado y capa con lo de debajo.
_RELATIONS = (
    ("parte_superior", "parte_inferior"),
    ("parte_inferior", "calzado"),
    ("capa_exterior", "parte_superior"),
)


def pair_key(a, b) -> tuple:
    """La misma clave para (a, b) y (b, a)."""
    return (a, b) if a <= b else (b, a)


@lru_cache(maxsize=1)
def _tables() -> dict:
    raw = json.loads(_FILE.read_text(encoding="utf-8"))

    def pairs(section: str) -> dict:
        return {pair_key(row["a"], row["b"]): float(row["score"]) for row in raw.get(section, [])}

    return {
        "colors": pairs("color_pairs"),
        "styles": pairs("style_pairs"),
        "patterns": pairs("pattern_pairs"),
        "types": pairs("type_pairs"),
        "layers": {(row["capa"], row["arriba"]): float(row["score"]) for row in raw.get("layer_over_top", [])},
    }


# ---------- Vocabulario común (reglas y gustos)


def is_denim(piece) -> bool:
    return piece.type == "vaquero" and piece.color in ("azul", "celeste")


def tone(piece) -> str:
    """El color con el que se empareja la prenda: el suyo, o «vaquero» si es un vaquero azul."""
    return DENIM if is_denim(piece) else piece.color


def is_neutral(piece) -> bool:
    return piece.color in NEUTRALS or is_denim(piece)


def loudness(pieces: list) -> int:
    """De 0 (todo liso y neutro) a 3 (muy cargado): colores fuertes distintos más estampados. Un color
    que aún no se sabe ("": una zapatilla de tienda sin ficha) no cuenta como color fuerte."""
    strong = len({p.color for p in pieces if p.color and not is_neutral(p)})
    patterns = sum(1 for p in pieces if p.pattern not in ("liso", "texturizado"))
    return min(3, strong + patterns)


def has_zip(piece) -> bool:
    """Cremallera entera. Si la prenda aún no tiene palabras clave, se busca en el texto."""
    if piece.closure is not None:
        return piece.closure == "cremallera"
    return "cremallera" in (piece.details or "").lower()


def zip_clash(layer, top) -> bool:
    return top.type == "sudadera" and layer.type in ("chaqueta", "sobrecamisa") and has_zip(top)


def relations(pieces: list) -> list[tuple]:
    """Las parejas de la combinación donde importa el tipo de prenda."""
    slot = {p.category: p for p in pieces}
    return [(slot[a], slot[b]) for a, b in _RELATIONS if a in slot and b in slot]


def traits(pieces: list) -> list[tuple]:
    """Rasgos de la combinación que salen de las palabras clave (corte, capucha, grosor, cierre).

    Las reglas no dicen nada de la mayoría; sirven para que Gustos aprenda cosas como «una chaqueta
    sobre algo con capucha sí» o «ancho arriba y ajustado abajo no».
    """
    slot = {p.category: p for p in pieces}
    top, bottom, layer = slot.get("parte_superior"), slot.get("parte_inferior"), slot.get("capa_exterior")
    keys = []
    if top and bottom and top.fit and bottom.fit:
        keys.append(("corte", top.fit, bottom.fit))
    if top and layer:
        if top.hood:
            keys.append(("capa", layer.type, "capucha"))
        if top.thickness == "grueso":
            keys.append(("capa", layer.type, "grueso"))
        if has_zip(top):
            keys.append(("capa", layer.type, "cremallera"))
    return keys


def blend(values: list[float]) -> float:
    """La media, tirando hacia abajo si alguna pareja choca. Con una sola pareja es su valor."""
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return mean + WEAKEST_LINK * (min(0.0, min(values)) - min(0.0, mean))


def remember(memo: dict | None, name: str, a, b, compute) -> float:
    """Cada pareja de prendas se calcula una sola vez por petición, aunque salga en miles de combinaciones."""
    if memo is None:
        return compute(a, b)
    key = (name, a.id, b.id)
    if key not in memo:
        memo[key] = compute(a, b)
    return memo[key]


# ---------- Las reglas


def _trust(seen, table: str, key) -> float:
    """De 1 (nadie ha opinado: manda la regla) hacia 0 (el usuario ya ha valorado esto muchas veces)."""
    return 1.0 if seen is None else TRUST_HALF / (TRUST_HALF + seen(table, key))


def pair_rule(a, b, seen=None) -> float:
    """Colores, estilos y estampados de una pareja de prendas."""
    t = _tables()
    color = DENIM_SCORE if is_denim(a) or is_denim(b) else t["colors"].get(pair_key(a.color, b.color), 0.0)
    styles = pair_key(a.style, b.style)
    return (
        W_COLOR * color * _trust(seen, "colors", pair_key(tone(a), tone(b)))
        + W_STYLE * (t["styles"].get(styles, SAME_REGISTER) - SAME_REGISTER) * _trust(seen, "styles", styles)
        + W_PATTERN * t["patterns"].get(pair_key(a.pattern, b.pattern), 0.0)
    )


def relation_rule(a, b, seen=None) -> float:
    """El tipo de prenda en una de las `relations`: arriba-abajo, abajo-calzado o capa-arriba."""
    t = _tables()
    types = pair_key(a.type, b.type)
    if a.category != "capa_exterior":
        return W_TYPE * t["types"].get(types, 0.0) * _trust(seen, "types", types)
    layer, top = a, b
    value = t["layers"].get((layer.type, top.type), 0.0) * _trust(seen, "types", types)
    if layer.type != "abrigo":
        if top.thickness == "grueso":
            value += BULKY_UNDER_LAYER * _trust(seen, "traits", ("capa", layer.type, "grueso"))
        if top.fit == "ancho" and layer.fit == "ajustado":
            value += BULKY_UNDER_LAYER
    if layer.hood and top.hood:
        value += DOUBLE_HOOD
    return W_TYPE * value


def palette(pieces: list, seen=None) -> float:
    """Los colores del conjunto entero: varios colores fuertes compitiendo restan (sin contar uno aún
    desconocido)."""
    strong = len({p.color for p in pieces if p.color and not is_neutral(p)})
    if strong <= 1:
        return 0.0
    return CROWDED_PALETTE * (strong - 1) * _trust(seen, "loud", loudness(pieces))


def prior(pieces: list, seen=None, memo: dict | None = None) -> float:
    """Cuánto sube o baja una combinación según las reglas generales. Sirve para Item y para Piece.

    `seen(tabla, clave)` dice cuántos votos hay ya sobre cada cosa (Taste.seen): a más votos, menos regla.
    """
    related = relations(pieces)
    total = palette(pieces, seen)
    total += blend([
        remember(memo, "regla", a, b, lambda a, b: pair_rule(a, b, seen))
        for a, b in itertools.combinations(pieces, 2)
    ])
    total += blend([remember(memo, "tipo", a, b, lambda a, b: relation_rule(a, b, seen)) for a, b in related])
    if any(a.category == "capa_exterior" and zip_clash(a, b) for a, b in related):
        total += ZIP_CLASH
    return total
