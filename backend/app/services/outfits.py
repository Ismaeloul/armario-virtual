"""Propone el outfit del día y calcula la afinidad de una combinación. No hay IA aquí.

La nota de una combinación tiene tres capas, de la que más manda a la que menos:

  1. Reglas del usuario, que no se negocian: ropa de verano solo del 1 de mayo al 30 de septiembre,
     nada de cazadora o sobrecamisa sobre una sudadera con cremallera entera, no repetir una
     combinación ya propuesta, con frío siempre una capa exterior si hay alguna que valga, una
     camiseta debajo de la sudadera con cremallera entera, y nada por debajo de una afinidad mínima
     mientras haya algo mejor. (Lo que está en la lavadora ni llega hasta aquí.)
  2. Cuánto pegan las prendas entre sí (`harmony`): las reglas generales de style_rules.py más lo
     aprendido en Gustos (taste.py). Es lo único que cuenta para la afinidad que se enseña, así que
     Hoy y Gustos dan el mismo porcentaje a la misma combinación.
  3. El día: temporada, grosor y capa según el tiempo, lo usado hace poco y los favoritos. Solo
     decide qué se propone hoy, no cambia la afinidad.
"""
import heapq
import itertools
import math
import os
import random
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import style_rules

# Se reexporta para quien solo quiera saber qué colores son neutros.
NEUTRALS = style_rules.NEUTRALS

# Temperatura máxima del día a partir de la cual hace calor / por debajo de la cual hace frío.
WARM_FROM = 23
COLD_UNTIL = 13
LAYER_UNTIL = 17  # con esta máxima o menos se añade una capa exterior
RAIN_LAYER_FROM = 60  # % de probabilidad de lluvia que también pide capa

# --- Reglas que no se negocian: restan tanto que solo salen si no hay ninguna otra cosa que proponer.
# Ropa de verano fuera de sus meses, aunque un día suelto suba la temperatura
# (decisión del usuario: 15 °C en invierno no es día de pantalón corto).
OUT_OF_SEASON = -30.0
WRONG_SEASON = -15.0  # prenda de invierno con calor, o de verano con frío

# --- El día (por prenda). Cifras pequeñas a propósito: matizan, pero manda cuánto pega la combinación.
# La prenda de la época vale 0 y las demás restan: así llevar una prenda más (la capa) no da nota por sí solo.
SEASON_FIT = {
    "calor": {"verano": 0.0, "todo_el_ano": -0.5, "invierno": WRONG_SEASON},
    "frio": {"invierno": 0.0, "todo_el_ano": -0.5, "verano": WRONG_SEASON},
    "templado": {"todo_el_ano": 0.0, "invierno": -0.5, "verano": -0.5},
}
FAVORITE = 0.5
NEVER_WORN = 0.3  # sin estrenar: un pequeño empujón
FORGOTTEN = 0.2  # lleva semanas sin salir del armario
FORGOTTEN_AFTER_DAYS = 21
WORN_YESTERDAY, WORN_LATELY = -2.5, -1.0  # ayer u hoy / hace dos o tres días
# Repetir camiseta dos días seguidos se nota; repetir zapatillas o chaqueta, no.
RECENCY_WEIGHT = {"parte_superior": 1.0, "parte_inferior": 0.6, "capa_exterior": 0.3, "calzado": 0.2}
# El grosor (palabra clave) afina lo que la temporada no dice.
THICK_WHEN_HOT, THIN_WHEN_HOT, THICK_WHEN_COLD, THIN_LAYER_WHEN_COLD = -1.5, 0.3, 0.5, -0.5
# Qué capa para qué temperatura (bandas de style_rules.json): abrigo hasta 10 °C, de sobra desde 14 °C;
# una sobrecamisa se queda corta por debajo de 8 °C.
COAT_UNTIL, COAT_TOO_WARM_FROM, OVERSHIRT_FROM = 10, 14, 8
COAT_WHEN_COLD, COAT_WHEN_MILD, OVERSHIRT_WHEN_COLD = 1.0, -2.0, -1.0
# Si el día pide capa, ir sin ella resta: lo justo para que solo pase cuando ninguna capa encaja.
NO_LAYER = {"frio": -2.0, "templado": -1.0}
# Una sudadera con cremallera entera no admite cazadora encima, pero ella misma hace de capa: en un día
# templado ir solo con ella no resta nada, y con frío, la mitad. Si no, no saldría nunca.
ZIP_HOODIE_AS_LAYER = {"frio": 0.5, "templado": 0.0}

# Azar para no proponer siempre lo mismo: un poco por prenda (así no gana cada día la misma chaqueta por
# una décima) y un poco por combinación. Juntos quedan por debajo de la diferencia entre una combinación
# corriente y una valorada con «me gusta», para que no tapen lo aprendido.
ITEM_NOISE, NOISE = 0.5, 0.5
# Con armarios muy grandes solo se completan con calzado y capa las mejores parejas arriba + abajo.
MAX_COMBOS = 20_000

# --- Afinidad: nota -> porcentaje. AFFINITY_MID es la nota de una combinación corriente (50 %); con
# AFFINITY_SCALE, una que cumple todas las reglas generales sin ningún voto ronda el 75 %, y solo
# pasan de 90 % las que el usuario ha confirmado. Cuando haya valoraciones reales, estas dos cifras
# se pueden ajustar para que el porcentaje sea la probabilidad de «me gusta» (regresión logística).
AFFINITY_MID, AFFINITY_SCALE = 0.7, 1.2
# Por debajo de esta afinidad Hoy no propone la combinación mientras quede alguna que llegue
# (decisión del usuario: que no recomiende cosas que no quedan bien).
MIN_AFFINITY = 60
# Las dos mitades de un conjunto (un chándal) juntas: ventaja al competir por ser el outfit de hoy.
# No cambia la afinidad que se enseña; separadas se siguen pudiendo proponer.
PAIR_TOGETHER = 3.0


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
    hood: bool | None = None
    pair_id: int | None = None  # la otra mitad del conjunto


@dataclass
class Proposal:
    items: list[Item]
    score: float
    affinity: int  # 0-100, para mostrar
    day_kind: str  # "calor", "frio" o "templado"
    with_layer: bool
    # "sin_capa", "sin_calzado", "sin_mas_combinaciones", "afinidad_baja", "sin_camiseta"
    notes: list[str] = field(default_factory=list)

    @property
    def ids(self) -> list[int]:
        return [item.id for item in self.items]


def local_today() -> date:
    """La fecha en casa del usuario. El contenedor va en UTC: sin esto, de madrugada «hoy» sería ayer."""
    try:
        return datetime.now(ZoneInfo(os.environ.get("ARMARIO_TZ", "Europe/Paris"))).date()
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return date.today()  # sin datos de zonas horarias (Windows sin tzdata): vale la hora del equipo


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


# La IA escribe tanto «manga corta» como «mangas cortas amplias». Las tiendas de Francia, en francés:
# «manches courtes» / «manches longues».
# Y en inglés (Nike, Carhartt WIP): «S/S T-Shirt», «L/S Shirt», «long sleeve».
_SHORT_SLEEVE = re.compile(r"mangas? cortas?|manches? courtes?|short[- ]sleeves?|(?<![a-z])s/s(?![a-z])")
_LONG_SLEEVE = re.compile(r"mangas? largas?|manches? longues?|long[- ]?sleeves?|(?<![a-z])l/s(?![a-z])")


def summer_only(item) -> bool:
    """Pantalón corto, manga corta y todo lo marcado como de verano."""
    if item.season == "verano" or item.type == "pantalón corto":
        return True
    if item.season == "invierno":
        return False  # una camiseta marcada de invierno no es de manga corta
    text = (getattr(item, "details", "") or "").lower()
    if _LONG_SLEEVE.search(text):
        return False
    return bool(_SHORT_SLEEVE.search(text)) or item.type in ("camiseta", "polo")


# ---------- El día


def _season_fit(item: Item, kind: str, today: date | None = None) -> float:
    if today is not None and not warm_months(today) and summer_only(item):
        return OUT_OF_SEASON
    return SEASON_FIT[kind][item.season]


def _recency(item: Item) -> float:
    days = item.days_since_worn
    if days is None:
        return NEVER_WORN
    if days >= FORGOTTEN_AFTER_DAYS:
        return FORGOTTEN
    weight = RECENCY_WEIGHT.get(item.category, 1.0)
    if days <= 1:
        return WORN_YESTERDAY * weight
    return WORN_LATELY * weight if days <= 3 else 0.0


def _warmth(item: Item, kind: str, temp_max: float | None) -> float:
    """El grosor de la prenda y, si es una capa, si es la adecuada para la temperatura."""
    value = 0.0
    if kind == "calor":
        value += {"grueso": THICK_WHEN_HOT, "fino": THIN_WHEN_HOT}.get(item.thickness, 0.0)
    elif kind == "frio":
        if item.thickness == "grueso":
            value += THICK_WHEN_COLD
        elif item.thickness == "fino" and item.category == "capa_exterior":
            value += THIN_LAYER_WHEN_COLD
    if item.type == "abrigo":
        if temp_max is None:
            value += COAT_WHEN_COLD if kind == "frio" else COAT_WHEN_MILD
        elif temp_max <= COAT_UNTIL:
            value += COAT_WHEN_COLD
        elif temp_max >= COAT_TOO_WARM_FROM:
            value += COAT_WHEN_MILD
    elif item.type == "sobrecamisa" and temp_max is not None and temp_max < OVERSHIRT_FROM:
        value += OVERSHIRT_WHEN_COLD
    return value


def _day_fit(item: Item, kind: str, today: date | None = None, temp_max: float | None = None) -> float:
    """Lo que suma o resta una prenda por el día que hace, lo reciente que se usó y si es favorita."""
    return (
        _season_fit(item, kind, today)
        + _warmth(item, kind, temp_max)
        + _recency(item)
        + (FAVORITE if item.favorite else 0.0)
    )


# ---------- Cuánto pega una combinación


def harmony(pieces: list, taste=None, memo: dict | None = None) -> float:
    """Reglas generales + lo aprendido, sin mirar el tiempo. Sirve para Item y para taste.Piece.

    Va de unos -12 (prohibido) a +8 (confirmado muchas veces); una combinación corriente ronda AFFINITY_MID.
    No depende de cuántas prendas lleve la combinación.
    """
    if taste is None:
        return style_rules.prior(pieces, memo=memo)
    return style_rules.prior(pieces, taste.seen, memo) + taste.adjust(pieces, memo)


def combo_affinity(pieces: list, taste=None, memo: dict | None = None) -> int:
    """El porcentaje que se enseña, en Hoy y en Gustos: de 1 a 99, solo según cuánto pega la combinación."""
    value = (harmony(pieces, taste, memo) - AFFINITY_MID) / AFFINITY_SCALE
    return max(1, min(99, round(100 / (1 + math.exp(-value)))))


def needs_undershirt(top) -> bool:
    """Una sudadera con la cremallera entera va abierta o medio abierta: debajo hace falta una camiseta."""
    return top.type == "sudadera" and style_rules.has_zip(top)


def without_undershirt(pieces: list) -> list:
    """La combinación sin la camiseta que va debajo de la sudadera con cremallera: lo que se valora y lo
    que no hay que repetir es la sudadera con lo demás, no qué camiseta tocó debajo."""
    if not any(needs_undershirt(p) for p in pieces):
        return list(pieces)
    return [p for p in pieces if p.type != "camiseta"]


def _undershirt(top: Item, combo: list[Item], tees: list[Item], taste, memo: dict) -> Item | None:
    """La camiseta que mejor va debajo: la que más pega con lo de abajo y el calzado, y que no se usó ayer.
    La temporada no cuenta: debajo de una sudadera una camiseta de manga corta vale todo el año."""
    rest = [p for p in combo if p.category in ("parte_inferior", "calzado")]
    return max(
        tees,
        key=lambda tee: harmony([tee, *rest], taste, memo) + _recency(tee) + (FAVORITE if tee.favorite else 0.0),
        default=None,
    )


def score(
    items: list[Item], kind: str, today: date | None = None, taste=None, temp_max: float | None = None,
    memo: dict | None = None,
) -> float:
    """La nota con la que compite una combinación para ser el outfit de hoy."""
    return harmony(items, taste, memo) + sum(_day_fit(item, kind, today, temp_max) for item in items)


def propose(
    items: list[Item],
    temp_max: float | None,
    rain_probability: int,
    today: date,
    avoid: list[set[int]] | None = None,
    rng: random.Random | None = None,
    taste=None,  # services.taste.Taste: lo aprendido en la pestaña Gustos
) -> Proposal | None:
    """Elige un outfit entre las prendas disponibles (las de la lavadora ya vienen quitadas).

    `avoid` son combinaciones que no hay que repetir (las elegidas estos días y las ya propuestas hoy),
    de la más antigua a la más reciente. Si ya no queda ninguna otra, repite la que hace más que
    salió y lo avisa con la nota "sin_mas_combinaciones".
    Devuelve None si no hay, como mínimo, una parte superior y una inferior.
    """
    rng = rng or random.Random()
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
    # Ir sin capa siempre es una opción (con su penalización): así nunca se fuerza una capa que choca.
    layers: list[Item | None] = [None, *layers_available] if layer_wanted else [None]
    no_layer = NO_LAYER[kind] if layer_wanted and layers_available else 0.0

    memo: dict = {}  # cada pareja de prendas se puntúa una sola vez, aunque salga en miles de combinaciones
    day = {item.id: _day_fit(item, kind, today, temp_max) for item in items}
    luck = {item.id: rng.uniform(0, ITEM_NOISE) for item in items}

    pairs = list(itertools.product(tops, bottoms))
    per_pair = len(shoes) * len(layers)
    if len(pairs) * per_pair > MAX_COMBOS:
        pairs = heapq.nlargest(
            max(50, MAX_COMBOS // per_pair),
            pairs,
            key=lambda pair: harmony(list(pair), taste, memo) + day[pair[0].id] + day[pair[1].id],
        )

    # (nota con azar, nota, cuánto pegan, combinación)
    candidates: list[tuple[float, float, float, list[Item]]] = []
    for (top, bottom), shoe, layer in itertools.product(pairs, shoes, layers):
        if layer is not None and style_rules.zip_clash(layer, top):
            continue  # regla del usuario; la misma combinación sin capa sigue en la lista
        combo = [piece for piece in (layer, top, bottom, shoe) if piece is not None]
        pegan = harmony(combo, taste, memo)
        value = pegan + sum(day[piece.id] for piece in combo)
        if layer is None:
            own_layer = top.type == "sudadera" and style_rules.has_zip(top)
            value += no_layer * (ZIP_HOODIE_AS_LAYER.get(kind, 1.0) if own_layer else 1.0)
        ids = {piece.id for piece in combo}
        if any(piece.pair_id in ids for piece in combo):
            value += PAIR_TOGETHER  # el conjunto entero (sudadera y pantalón del chándal)
        candidates.append(
            (value + sum(luck[piece.id] for piece in combo) + rng.uniform(0, NOISE), value, pegan, combo)
        )

    # Con frío, la capa exterior no es opcional: sin ella solo si ninguna combinación admite una
    # (decisión del usuario: «va a hacer frío, hay que poner abrigo»).
    if kind == "frio" and layers_available:
        layered = [c for c in candidates if c[3][0].category == "capa_exterior"]
        candidates = layered or candidates

    # Lo ya propuesto se compara sin la camiseta de debajo: es la misma combinación con otra camiseta.
    def key(pieces) -> frozenset:
        return frozenset(piece.id for piece in pieces)

    by_id = {item.id: item for item in items}
    last_seen: dict[frozenset, int] = {}
    for position, ids in enumerate(avoid or []):
        last_seen[key(without_undershirt([by_id[i] for i in ids if i in by_id]))] = position
        last_seen[frozenset(ids)] = position
    fresh = [c for c in candidates if key(c[3]) not in last_seen]
    notes = []
    if fresh:
        # Nada por debajo de la afinidad mínima mientras quede algo que llegue.
        floor = AFFINITY_MID + AFFINITY_SCALE * math.log(MIN_AFFINITY / (100 - MIN_AFFINITY))
        good = [c for c in fresh if c[2] >= floor]
        if not good:
            notes.append("afinidad_baja")
        _, value, _, combo = max(good or fresh, key=lambda c: c[0])
    else:
        # Todo lo posible ya ha salido: toca la que hace más que se propuso (nunca la que se acaba de ver,
        # salvo que sea la única que hay).
        notes.append("sin_mas_combinaciones")
        _, value, _, combo = min(candidates, key=lambda c: (last_seen.get(key(c[3]), -1), -c[0]))

    affinity = combo_affinity(combo, taste, memo)
    with_layer = any(piece.category == "capa_exterior" for piece in combo)
    # Debajo de la sudadera con cremallera entera, una camiseta. Va aparte de la nota y de la afinidad:
    # se elige al final, para la combinación que ya ha ganado.
    top = next(piece for piece in combo if piece.category == "parte_superior")
    if needs_undershirt(top):
        tee = _undershirt(top, combo, [item for item in tops if item.type == "camiseta"], taste, memo)
        if tee is None:
            notes.append("sin_camiseta")
        else:
            combo = [*combo[: combo.index(top) + 1], tee, *combo[combo.index(top) + 1:]]

    if layer_wanted and not layers_available:
        notes.append("sin_capa")
    if shoes == [None]:
        notes.append("sin_calzado")
    return Proposal(
        items=combo,
        score=value,
        affinity=affinity,
        day_kind=kind,
        with_layer=with_layer,
        notes=notes,
    )
