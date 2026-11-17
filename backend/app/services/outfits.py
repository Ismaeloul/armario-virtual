"""Propone el outfit del día con reglas sencillas (Fase 2).

No hay IA aquí: se puntúan todas las combinaciones posibles de las prendas disponibles y se
elige una de las mejores. En la Fase 3 estas reglas las irá sustituyendo un algoritmo que
aprenda de los "Me gusta" y los "Pasar"; por eso cada decisión del usuario ya se guarda.
"""
import itertools
import random
from dataclasses import dataclass, field
from datetime import date

from . import style_rules

# Colores que combinan con casi todo. El vaquero (azul o celeste) cuenta como neutro.
NEUTRALS = {"negro", "blanco", "gris", "beige", "crudo", "azul marino", "marrón"}
DENIM = {"vaquero"}

# Temperatura máxima del día a partir de la cual hace calor / por debajo de la cual hace frío.
WARM_FROM = 23
COLD_UNTIL = 13
LAYER_UNTIL = 17  # con esta máxima o menos se añade una capa exterior
RAIN_LAYER_FROM = 60  # % de probabilidad de lluvia que también pide capa


@dataclass
class Item:
    """Lo que el algoritmo necesita saber de una prenda."""

    id: int
    type: str
    category: str
    color: str
    style: str
    season: str
    favorite: bool = False
    pattern: str = "liso"
    days_since_worn: int | None = None  # None = nunca
    details: str = ""  # nombre y detalles en texto, por si la prenda aún no tiene palabras clave
    closure: str | None = None
    fit: str | None = None
    thickness: str | None = None


@dataclass
class Proposal:
    items: list[Item]
    score: float
    affinity: int  # 0-100, para mostrar
    day_kind: str  # "calor", "frio" o "templado"
    with_layer: bool
    notes: list[str] = field(default_factory=list)

    @property
    def ids(self) -> list[int]:
        return [item.id for item in self.items]


def day_kind(temp_max: float | None, today: date) -> str:
    """Qué tipo de día es. Sin dato del tiempo, se decide por el mes."""
    if temp_max is None:
        if today.month in (6, 7, 8, 9):
            return "calor"
        if today.month in (11, 12, 1, 2, 3):
            return "frio"
        return "templado"
    if temp_max >= WARM_FROM:
        return "calor"
    if temp_max <= COLD_UNTIL:
        return "frio"
    return "templado"


def wants_layer(kind: str, temp_max: float | None, rain_probability: int) -> bool:
    """¿Pide el día una capa exterior? Con calor nunca; con frío siempre; templado, si refresca o llueve."""
    if kind == "calor":
        return False
    return kind == "frio" or (temp_max is not None and temp_max <= LAYER_UNTIL) or rain_probability >= RAIN_LAYER_FROM


def warm_months(today: date) -> bool:
    """De mediados de primavera a final de verano: del 1 de mayo al 30 de septiembre."""
    return 5 <= today.month <= 9


def summer_only(item) -> bool:
    """Pantalón corto, manga corta y todo lo marcado como de verano."""
    if item.season == "verano" or item.type == "pantalón corto":
        return True
    text = (getattr(item, "details", "") or "").lower()
    if "manga larga" in text:
        return False
    return "manga corta" in text or item.type in ("camiseta", "polo")


# Fuera de esos meses la ropa de verano no se propone aunque un día suelto suba la temperatura
# (decisión del usuario: 15 °C en invierno no es día de pantalón corto).
OUT_OF_SEASON = -8.0


def _season_fit(item: Item, kind: str, today: date | None = None) -> float:
    if today is not None and not warm_months(today) and summer_only(item):
        return OUT_OF_SEASON
    if kind == "calor":
        return {"verano": 2, "todo_el_ano": 1, "invierno": -6}[item.season]
    if kind == "frio":
        return {"invierno": 2, "todo_el_ano": 1, "verano": -6}[item.season]
    return {"todo_el_ano": 2, "invierno": 0.5, "verano": 0.5}[item.season]


def _is_neutral(item: Item) -> bool:
    return item.color in NEUTRALS or (item.type in DENIM and item.color in {"azul", "celeste"})


def _color_harmony(items: list[Item]) -> float:
    loud = [item.color for item in items if not _is_neutral(item)]
    distinct = len(set(loud))
    if distinct == 0:
        return 1.5  # todo neutro: siempre funciona
    if distinct == 1:
        # Un solo color con protagonismo. Repetirlo arriba y abajo queda demasiado igual.
        return 2.0 if len(loud) == 1 else 0.5
    return -2.0 * (distinct - 1)  # varios colores fuertes compitiendo


def _style_fit(items: list[Item]) -> float:
    styles = {item.style for item in items}
    if len(styles) == 1:
        return 1.5
    if "formal" in styles and "deportivo" in styles:
        return -3.0
    return 0.0


def _recency(item: Item) -> float:
    if item.days_since_worn is None:
        return 0.3  # sin estrenar: un pequeño empujón
    if item.days_since_worn <= 1:
        return -2.5  # ayer u hoy
    if item.days_since_worn <= 3:
        return -1.0
    return 0.0


def score(items: list[Item], kind: str, today: date | None = None) -> float:
    total = sum(_season_fit(item, kind, today) +_recency(item) + (0.5 if item.favorite else 0) for item in items)
    return total + _color_harmony(items) + _style_fit(items) + style_rules.prior(items)


def _affinity(value: float, pieces: int) -> int:
    """Convierte la puntuación en un porcentaje legible. Es orientativo, no una medida real."""
    # Todo encaja de temporada, favorito, color y estilo perfectos, y las reglas generales a favor.
    best = pieces * 2.5 + 3.5 + 1.2 * pieces * (pieces - 1) / 2
    return max(40, min(99, round(55 + 44 * value / best)))


def propose(
    items: list[Item],
    temp_max: float | None,
    rain_probability: int,
    today: date,
    avoid: list[set[int]] | None = None,
    disliked_pairs: set[frozenset[int]] | None = None,
    rng: random.Random | None = None,
    taste=None,  # services.taste.Taste: lo aprendido en la pestaña Gustos
) -> Proposal | None:
    """Elige un outfit entre las prendas disponibles (las de la lavadora ya vienen quitadas).

    `avoid` son combinaciones que no hay que repetir (las ya propuestas hoy y las de los últimos días).
    Devuelve None si no hay, como mínimo, una parte superior y una inferior.
    """
    rng = rng or random.Random()
    avoid = avoid or []
    disliked_pairs = disliked_pairs or set()
    kind = day_kind(temp_max, today)

    by_category: dict[str, list[Item]] = {}
    for item in items:
        by_category.setdefault(item.category, []).append(item)

    tops, bottoms = by_category.get("parte_superior", []), by_category.get("parte_inferior", [])
    if not tops or not bottoms:
        return None
    shoes: list[Item | None] = list(by_category.get("calzado", [])) or [None]

    layers_available = by_category.get("capa_exterior", [])
    layer_wanted = wants_layer(kind, temp_max, rain_probability)
    layers: list[Item | None] = list(layers_available) if layer_wanted and layers_available else [None]

    candidates: list[tuple[float, float, list[Item]]] = []
    for top, bottom, shoe, layer in itertools.product(tops, bottoms, shoes, layers):
        combo = [piece for piece in (layer, top, bottom, shoe) if piece is not None]
        ids = {piece.id for piece in combo}
        value = score(combo, kind, today) + (taste.adjust(combo) if taste else 0.0)
        if frozenset((top.id, bottom.id)) in disliked_pairs:
            value -= 2.0  # esta pareja ya se descartó alguna vez
        penalty = 100.0 if any(ids == seen for seen in avoid) else 0.0
        candidates.append((value - penalty + rng.uniform(0, 1.5), value, combo))

    candidates.sort(key=lambda c: c[0], reverse=True)
    _, value, combo = candidates[0]

    notes = []
    if layer_wanted and not layers_available:
        notes.append("sin_capa")
    if shoes == [None]:
        notes.append("sin_calzado")
    return Proposal(
        items=combo,
        score=value,
        affinity=_affinity(value, len(combo)),
        day_kind=kind,
        with_layer=any(piece.category == "capa_exterior" for piece in combo),
        notes=notes,
    )


def combo_affinity(pieces: list, taste=None) -> int:
    """Afinidad de una combinación sin mirar el tiempo: solo colores, estilo y lo aprendido."""
    value = _color_harmony(pieces) + _style_fit(pieces) + style_rules.prior(pieces)
    value += taste.adjust(pieces) if taste else 0.0
    # Casi todo se suma por parejas de prendas, así que se reparte entre ellas: si no, cuatro prendas
    # puntuarían siempre más que dos.
    pairs = len(pieces) * (len(pieces) - 1) / 2
    return max(10, min(99, round(40 + 20 * value / (1 + 0.9 * pairs))))
