"""Compras (Fase 4): trae el catálogo de las tiendas, lo puntúa contra el armario y lleva su estado.

Aquí no hay IA. La nota de un producto sale, de lo que más pesa a lo que menos, de:

  1. Lo que el usuario ha ido diciendo en la propia pestaña con «me gusta» / «no me gusta»:
     tipo de prenda, color, palabras del nombre («pana», «relaxed»…) y franja de precio.
  2. Que se parezca a lo que ya lleva: que el color sea de los suyos (y lo lleve en esa parte del
     cuerpo), que combine con su armario (la misma afinidad de Hoy y Gustos, pareja a pareja) y que
     no sea un corte o un estampado raro.
  3. Los huecos del armario (un tipo que no hay, un color base que falta, una categoría corta) y lo
     repetido: solo como desempate.

Con cero valoraciones gana la ropa básica y ponible, no la pieza llamativa: lo raro resta.

Cada consulta semanal guarda el catálogo entero ya normalizado como «candidatos» (filas de
`shop_items` sin fotos) y solo baja detalle y fotos de los mejores. «Ver más» vuelve a puntuar los
candidatos con los gustos de ese momento y baja la tanda siguiente.

La IA solo entra cuando el usuario marca «La he comprado»: entonces se analizan las fotos guardadas
y la prenda pasa al armario. La app nunca compra ni guarda datos de pago: solo enlaza a la tienda.

Aparte está el buscador (`lookup`): el usuario da una referencia, un enlace o un texto, y lo que
sale se guarda como «buscado» con sus fotos, listo para pasar a Me gustan o al armario. Un «buscado»
no es una propuesta: no sale en Descubrir ni enseña nada hasta que se guarda o se compra.

Un producto puede existir en varios colores, y cada color es un item aparte. Con la ficha se apuntan
los colores hermanos (`siblings`); elegir otro (`switch_color`) trae ese item, y en Descubrir solo se
enseña uno a la vez: el otro queda apartado («variante»). «Combina con…» (`matches`) dice con qué
prendas del armario va mejor un producto, con la misma afinidad de Hoy y Gustos.
"""
import json
import logging
import math
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from datetime import time as dtime
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, object_session

from .. import catalog, config
from ..db import SessionLocal
from ..models import Garment, Setting, ShopItem, now_utc
from . import ai, outfits, shops, storage, style_rules
from .ai.base import build_prompt
from .ai import codex_models
from .shops import BlockedError, BrowserUnavailable, Cancelled, NeedsBrowser, NotThisStore, Partial, SearchError
from .shops import ShopError
from .shops.estimate import brand_family, estimate_color, norm

UNKNOWN_HEX = "#9e9e9e"  # el circulito de un color que no se sabe: un gris medio, sin decir nada

log = logging.getLogger("armario.compras")

# «candidato»: está en el catálogo de la tienda pero no se ha enseñado (no tiene fotos).
CANDIDATE = "candidato"
NEW, LIKED, DISCARDED, BOUGHT, EXPIRED = "nuevo", "gustado", "descartado", "comprado", "caducado"
# «buscado»: lo trajo el buscador y aún no se ha hecho nada con él. Tiene fotos, pero no es una
# propuesta: no sale en Descubrir, no es candidato y no enseña nada. Si no se guarda ni se compra,
# se limpia solo (`clean_lookups`).
SEARCHED = "buscado"
# «variante»: otro color de una propuesta de Descubrir, apartado al elegir color. De un producto solo
# se enseña un color a la vez: el que no se está viendo ni sale como propuesta aparte, ni cuenta como
# descartado, ni enseña nada. Guarda sus fotos (para volver a él al momento) hasta la consulta semanal.
VARIANT = "variante"

MATCH_PER_GROUP = 3  # prendas del armario que se enseñan por parte del cuerpo en «Combina con»
# Afinidad mínima de la pareja para salir en «Combina con»: la de una combinación corriente. Es más
# baja que GOOD_PAIR (la que cuenta para la nota) a propósito: con GOOD_PAIR, a una prenda normal le
# salían grupos enteros vacíos (una sudadera gris sin ningún calzado), y aquí lo que se pide son las
# mejores de cada parte del cuerpo, no solo las redondas. Lo que queda por debajo no se enseña.
MATCH_MIN = 50
COMPOSITION_MAX = 300

LOOKUP_MAX = 12  # resultados del buscador, como mucho (un producto con muchos colores)
LOOKUP_SECONDS = 40.0  # a partir de aquí no se piden más fichas: se enseña lo que haya
LOOKUP_KEEP = timedelta(hours=24)  # lo que dura un «buscado» con el que no se hace nada
# La consulta semanal también los limpia, salvo los de hace un momento: puede haber una búsqueda abierta.
LOOKUP_KEEP_ON_REFRESH = timedelta(hours=1)

LIKED_DAYS = 30  # lo que dura un «me gusta» antes de caducar
BOUGHT_WEIGHT = 3.0  # una compra enseña tanto como tres «me gusta»
LAPSED_WEIGHT = 0.5  # un «me gusta» que caducó o se quitó sin comprar
EXPIRES_SOON_DAYS = 5  # desde cuándo se avisa de que caduca pronto
DESCRIPTION_MAX = 400  # caracteres de la descripción de la tienda que se guardan en `details`

# ---------- Pesos de la nota (de 0 a 100)
#
# Todo producto sale de BASE y suma o resta. Los tres bloques, de más a menos peso:

BASE = 30.0

# 1. Lo que el usuario acepta y descarta en la tienda. Cada opinión va de -1 a 1 (ver ShopTaste.opinion),
#    así que este bloque mueve la nota hasta ±56: manda sobre todo lo demás en cuanto hay valoraciones.
#    Además, un color o un corte que el usuario ya ha aceptado deja de restar en el bloque 2.
W_PREF_TYPE = 16.0  # tipo de prenda («sueles descartar los polos»)
W_PREF_COLOR = 16.0  # color
W_PREF_WORD = 16.0  # palabras del nombre (cropped, pana, relaxed…), sumadas y topadas en ±1
# La marca (Nike, Adidas, New Balance…), en las tiendas que venden varias. Pesa menos que el tipo y el
# color: «te gustan las Nike» no debe tapar que una zapatilla concreta no va con el armario.
W_PREF_BRAND = 10.0
# El precio NO cuenta (decisión del usuario, 18-11-2026): ni suma, ni resta, ni sale como motivo.
# Se sigue apuntando por franjas por si algún día se quiere usar.
W_PREF_PRICE = 0.0
PREF_PRIOR_VOTES = 2.0  # votos neutros de relleno: una sola opinión no decide
USUAL_PRIOR_VOTES = 10.0  # votos de relleno al calcular cuánto acepta el usuario en general
CLEAR_PREF = 0.35  # opinión a partir de la cual se enseña como motivo

# 2. Que se parezca a lo que ya lleva. Sin valoraciones es lo que decide: hasta +44 y hasta -48.
W_MATCH = 22.0  # por la fracción de prendas complementarias del armario con las que combina
GOOD_PAIR = 60  # afinidad de la pareja producto + prenda desde la que se cuenta que «combina»
W_PALETTE = 16.0  # el color es de los que ya lleva: cuanto más lo usa, más suma
PALETTE_FULL = 0.2  # con esta fracción del armario en ese color, la suma es completa
OFF_PALETTE = -16.0  # un color fuerte del que no tiene nada: no es un hueco, es que no lo lleva
OFF_CATEGORY = -8.0  # lleva ese color, pero no en esa parte del cuerpo (vaquero blanco, zapatilla beige)
HABIT_MIN = 8  # prendas que hacen falta en la categoría para decir «en esto no llevas ese color»
W_BASIC = 6.0  # liso y de color base: va con todo
LOUD = -6.0  # un estampado (rayas, cuadros, gráfico…) que no hay en todo el armario
RISKY = -18.0  # corte o acabado poco habitual, por el nombre (ver _RISKY)

# 3. Huecos del armario y repetidos: desempate entre dos prendas igual de ponibles, nunca el motor.
GAP_TYPE = 4.0  # el armario no tiene ninguna prenda de ese tipo
GAP_COLOR = 2.0  # tiene el tipo, pero no en ese color; solo si es un color base
GAP_CATEGORY = 3.0  # la categoría entera tiene muy pocas prendas…
FEW_IN_CATEGORY = 3  # …menos de estas
DUPLICATE = -4.0  # por cada prenda del mismo tipo y color que ya hay (hasta MAX_DUPLICATES)
MAX_DUPLICATES = 2

# Cuando la nota media de una tanda de «Ver más» baja de aquí, la interfaz avisa de que lo que
# viene ya encaja menos.
LOW_FIT = 50.0

# Al elegir qué candidatos se traen (no al puntuarlos), cada repetido baja un poco para que la tanda
# sea variada: ocho chinos negros con la misma nota no deben llenarla.
REPEAT_STEP = 4.0  # por cada candidato ya elegido del mismo tipo y color
SECTION_STEP = 2.0  # por cada candidato ya elegido de la misma categoría de la tienda

# Cortes y acabados poco habituales en ropa de diario. Zara Hombre los mezcla con lo básico y, sin
# mirar la foto, el nombre es lo único que los delata. Es solo el punto de partida: si al usuario le
# gusta alguno, lo aprendido por palabras quita la penalización.
_RISKY = re.compile(
    r"\b(cropped|culotte|flare|acampanad[oa]s?|crochet|calad[oa]s?|transparentes?|lentejuelas|brillos?|"
    r"satinad[oa]s?|metalizad[oa]s?|limited|faldas?|top|sandalias?|zuecos?|flores|floral|bordad[oa]s?|"
    r"jacquard|rejilla|leopardo|balloon|pareo|kimono|plumas|"
    # Lo mismo en francés (Zara Francia).
    r"evase|evasee|ajoure|ajouree|transparente?s?|paillettes|brillante?s?|satine|satinee|metallise|metallisee|"
    r"jupes?|sandales?|sabots?|fleurs|fleuri|brode|brodee|resille|leopard|plumes)\b"
)

# A quién se le echa la culpa de un «no me gusta», según el motivo que dé el usuario:
# (tipo, color, precio, palabras). Sin motivo se reparte entre todo, más flojo.
DISCARD_REASONS = ("estilo", "color", "caro", "ya_tengo")
_BLAME = {
    # Descartar no es decir «no me gusta este tipo de ropa»: puede ser una manga o un detalle. Por eso
    # un descarte cuenta muy poco (un «me gusta» cuenta 1) y solo pesa cuando se repite muchas veces.
    None: (0.2, 0.2, 0.2, 0.2),
    "estilo": (0.5, 0.0, 0.0, 1.0),  # el corte: las palabras del nombre y, algo, el tipo
    "color": (0.0, 1.0, 0.0, 0.0),
    "caro": (0.0, 0.0, 1.0, 0.0),
    "ya_tengo": (0.0, 0.0, 0.0, 0.0),  # no dice nada de sus gustos
}

# Franjas de precio, en céntimos: hasta 25 €, hasta 50 €, hasta 80 € y más.
PRICE_BANDS = ((2500, "hasta_25"), (5000, "hasta_50"), (8000, "hasta_80"))

# --- Claves de la tabla settings
K_STORES, K_CATEGORIES = "shop_stores", "shop_categories"
K_STATUS = "shop_status"  # tienda -> cómo fue su última consulta (ver `store_status`)
K_MORE = "shop_more"  # cómo fue el último «Ver más» (ver `more`); None tras cada consulta semanal
K_NIGHT = "shop_night_time"  # a qué hora (local, «HH:MM») se hace la consulta automática
K_ENABLED_AT = "shop_enabled_at"  # tienda -> cuándo se activó (UTC): la primera consulta es esa noche
K_NIGHT_RUNS = "shop_night_runs"  # {"night": día, "stores": [...]}: las que ya salieron esa noche (ver `tonight`)
DEFAULT_NIGHT = "03:30"
_HHMM = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")


# ---------- Ajustes de la pestaña


def _get(db: Session, key: str, default=None):
    row = db.get(Setting, key)
    if row is None:
        return default
    try:
        return json.loads(row.value)
    except ValueError:
        return default


def _set(db: Session, key: str, value) -> None:
    db.merge(Setting(key=key, value=json.dumps(value, ensure_ascii=False)))


def enabled_stores(db: Session) -> list[str]:
    """Las tiendas activadas. Ninguna por defecto: el usuario las activa en la pestaña."""
    stored = _get(db, K_STORES, [])
    return [key for key in shops.CONNECTORS if key in (stored or [])]


def active_categories(db: Session, store: str) -> list[str]:
    """Las categorías de una tienda que interesan (todas, si el usuario no ha elegido)."""
    connector = shops.CONNECTORS[store]
    chosen = (_get(db, K_CATEGORIES, {}) or {}).get(store)
    if chosen is None:
        return list(connector.categories)
    # Zara numera sus categorías igual en todos los países («-l855»): lo elegido con la tienda de otro
    # país (España) sigue valiendo.
    keys = {_category_key(slug) for slug in chosen}
    return [slug for slug in connector.categories if slug in chosen or _category_key(slug) in keys]


def _category_key(slug: str) -> str:
    match = re.search(r"-l\d+$", slug)
    return match.group() if match else slug


def set_store(db: Session, store: str, enabled: bool | None, categories: list[str] | None) -> None:
    if enabled is not None:
        stores = set(enabled_stores(db))
        if enabled and store not in stores:
            _set(db, K_ENABLED_AT, {**(_get(db, K_ENABLED_AT, {}) or {}), store: now_utc().isoformat()})
        stores.add(store) if enabled else stores.discard(store)
        _set(db, K_STORES, sorted(stores))
    if categories is not None:
        by_store = dict(_get(db, K_CATEGORIES, {}) or {})
        by_store[store] = [slug for slug in shops.CONNECTORS[store].categories if slug in categories]
        _set(db, K_CATEGORIES, by_store)
    db.commit()


def _aware(moment: datetime | None) -> datetime | None:
    """SQLite devuelve las fechas sin zona: son UTC."""
    if moment is not None and moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def _parse_day(value) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


# ---------- Estado de cada tienda y cuándo toca consultarla


def store_status(db: Session, store: str) -> dict | None:
    """Cómo fue la última consulta a una tienda, o None si aún no se ha consultado.

    {"at": cuándo (UTC), "day": día local, "ok": respondió, "ok_day": día local de la última que fue bien,
     "found": productos del catálogo, "added": propuestas nuevas, "expired": caducadas,
     "failed": peticiones que fallaron, "error": el primer fallo en claro, "errors": [todos]}
    """
    return (_get(db, K_STATUS, {}) or {}).get(store)


def _save_status(db: Session, store: str, status: dict) -> None:
    by_store = dict(_get(db, K_STATUS, {}) or {})
    by_store[store] = status
    _set(db, K_STATUS, by_store)


def check_day(store: str, today: date) -> date:
    """El último día de consulta de la tienda que ya ha llegado (hoy incluido).

    Cada tienda se consulta una vez por semana, en su día (`refresh_weekday` del conector: el siguiente
    al que saca novedades).
    """
    weekday = getattr(shops.CONNECTORS[store], "refresh_weekday", 0)
    return today - timedelta(days=(today.weekday() - weekday) % 7)


def night_time(db: Session) -> str:
    """La hora local («HH:MM») de la consulta automática. Por defecto, las 03:30."""
    value = _get(db, K_NIGHT, DEFAULT_NIGHT)
    return value if isinstance(value, str) and _HHMM.fullmatch(value) else DEFAULT_NIGHT


def set_night_time(db: Session, value: str) -> None:
    if not _HHMM.fullmatch(value or ""):
        raise ValueError("La hora va como HH:MM")
    _set(db, K_NIGHT, value)
    db.commit()


def _clock(db: Session) -> dtime:
    hours, minutes = night_time(db).split(":")
    return dtime(int(hours), int(minutes))


def local_now() -> datetime:
    """La hora de casa del usuario (`ARMARIO_TZ`), sin zona: con ella se compara la hora de la consulta."""
    try:
        return datetime.now(ZoneInfo(os.environ.get("ARMARIO_TZ", "Europe/Paris"))).replace(tzinfo=None)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return datetime.now()


def _to_local(moment: datetime | None) -> datetime | None:
    """Un instante en UTC a la hora local de casa, sin zona."""
    if moment is None:
        return None
    try:
        zone = ZoneInfo(os.environ.get("ARMARIO_TZ", "Europe/Paris"))
        return _aware(moment).astimezone(zone).replace(tzinfo=None)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return _aware(moment).astimezone().replace(tzinfo=None)


def _parse_moment(value) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def due_at(db: Session, store: str, today: date | None = None) -> datetime | None:
    """Cuándo (hora local, sin zona) toca la próxima consulta automática de la tienda; None si está
    desactivada.

    - Su día de la semana, a la hora de la noche (`night_time`), salvo que desde ese día ya haya una
      consulta completa (p. ej. con «Consultar ahora»): entonces, el mismo día de la semana siguiente.
    - Si la de hoy falló o quedó a medias, la noche siguiente (se retoma por donde iba).
    - Recién activada y sin consultar nunca: la primera noche después de activarla.
    Si la app estaba apagada a esa hora, el momento ya ha pasado: toca en cuanto arranque.
    """
    if store not in enabled_stores(db):
        return None
    today = today or outfits.local_today()
    clock = _clock(db)
    status = store_status(db, store) or {}
    cycle_day = check_day(store, today)
    ok_day = _parse_day(status.get("ok_day"))
    if ok_day and ok_day >= cycle_day:
        return datetime.combine(cycle_day + timedelta(days=7), clock)
    moment = datetime.combine(cycle_day, clock)
    attempted = _parse_day(status.get("day"))
    if attempted is None and not status:
        enabled_at = _to_local(_parse_moment((_get(db, K_ENABLED_AT, {}) or {}).get(store)))
        if enabled_at is not None:
            first = datetime.combine(enabled_at.date(), clock)
            moment = first if first > enabled_at else first + timedelta(days=1)
    if attempted is not None and attempted >= cycle_day:
        moment = max(moment, datetime.combine(attempted + timedelta(days=1), clock))
    return moment


def is_due(db: Session, store: str, today: date | None = None, now: datetime | None = None) -> bool:
    """¿Toca consultar ya esta tienda? `now` es la hora local (sin zona); sin ella, la de ahora. Si
    solo se da `today`, se mira a mediodía de ese día (para los tests y para «qué toca hoy»)."""
    if now is None:
        now = datetime.combine(today, dtime(12, 0)) if today is not None else local_now()
    moment = due_at(db, store, now.date())
    return moment is not None and now >= moment


def due_stores(db: Session, today: date | None = None, now: datetime | None = None) -> list[str]:
    return [store for store in enabled_stores(db) if is_due(db, store, today, now)]


def night_of(db: Session, now: datetime) -> date:
    """La noche a la que pertenece un momento (hora local): de la hora de la consulta de un día a la
    misma hora del siguiente. Así lo que arranca tarde (la app estaba apagada) cuenta en esa noche."""
    return now.date() if now.time() >= _clock(db) else now.date() - timedelta(days=1)


def tonight(db: Session, now: datetime | None = None) -> list[str]:
    """Las tiendas que se consultan ahora en la tanda automática, en orden: de las que ya toca, primero
    las que más llevan esperando, sin pasar de `SHOP_STORES_PER_NIGHT` por noche ni de
    `SHOP_HEAVY_PER_NIGHT` pesadas (ver shops/__init__.py). Las que no caben esperan a la noche siguiente:
    siguen tocando, y entonces van las primeras. «Consultar ahora» no pasa por aquí."""
    now = now or local_now()
    due = due_stores(db, now=now)
    if not due:
        return []
    night = night_of(db, now).isoformat()
    runs = _get(db, K_NIGHT_RUNS, {}) or {}
    ran = [s for s in runs.get("stores") or [] if isinstance(s, str)] if runs.get("night") == night else []
    order = list(shops.CONNECTORS)
    waiting = sorted(due, key=lambda s: (due_at(db, s, now.date()) or now, order.index(s)))
    picked: list[str] = []
    for store in waiting:
        if store in ran:
            continue
        if len(ran) + len(picked) >= config.SHOP_STORES_PER_NIGHT:
            break
        if shops.heavy(store) and sum(map(shops.heavy, ran + picked)) >= config.SHOP_HEAVY_PER_NIGHT:
            continue
        picked.append(store)
    return picked


def note_tonight(db: Session, stores: list[str], now: datetime | None = None) -> None:
    """Apunta que estas tiendas ya han salido esta noche (para el tope de `tonight`)."""
    now = now or local_now()
    night = night_of(db, now).isoformat()
    runs = _get(db, K_NIGHT_RUNS, {}) or {}
    ran = list(runs.get("stores") or []) if runs.get("night") == night else []
    _set(db, K_NIGHT_RUNS, {"night": night, "stores": ran + [s for s in stores if s not in ran]})
    db.commit()


def week_plan() -> list[list[str]]:
    """El reparto de la semana, para el panel: por día (lunes = 0), las tiendas que se consultan."""
    plan: list[list[str]] = [[] for _ in range(7)]
    for key, connector in shops.CONNECTORS.items():
        plan[int(getattr(connector, "refresh_weekday", 0)) % 7].append(key)
    return plan


def next_check(db: Session, store: str, today: date | None = None) -> date:
    """Qué día se consultará la tienda por su cuenta (hoy si ya toca)."""
    today = today or outfits.local_today()
    moment = due_at(db, store, today)
    return max(moment.date(), today) if moment is not None else today


def next_check_at(db: Session, store: str) -> datetime | None:
    """Cuándo (hora local) se consultará sola; si ya ha pasado (estaba apagada), ahora."""
    moment = due_at(db, store)
    return None if moment is None else max(moment, local_now().replace(second=0, microsecond=0))


def blocked_today(db: Session, store: str, today: date | None = None) -> str | None:
    """Si la tienda bloqueó hoy (el acceso o con un captcha), el motivo; si no, None. Hasta mañana no
    se le vuelve a preguntar, ni con «Consultar ahora» ni con «Ver más»."""
    today = today or outfits.local_today()
    status = store_status(db, store) or {}
    if status.get("blocked_day") == today.isoformat():
        return str(status.get("error") or shops.browser.BLOCKED_TEXT).split(": ", 1)[-1]
    return shops.browser.blocked(store)


def reachable(db: Session, store: str, today: date | None = None) -> bool:
    """¿Se le puede pedir algo hoy a la tienda? No si le falta el navegador o si ha bloqueado hoy."""
    return not shops.unavailable(store) and not blocked_today(db, store, today)


# ---------- Lo aprendido en la pestaña


_STOP_WORDS = {
    "con", "sin", "para", "por", "del", "los", "las", "the", "and", "zara", "hombre", "fit", "regular", "manga",
    "mangas", "larga", "corta", "basico", "basica", "pack", "edition", "cuello", "efecto", "tejido",
    # En francés (Zara Francia, Courir, JD Sports .fr).
    "avec", "sans", "pour", "des", "les", "une", "homme", "manche", "manches", "longue", "longues", "courte",
    "courtes", "basique", "col", "effet", "tissu", "coupe", "maille",
}


def name_words(name: str) -> set[str]:
    """Las palabras del nombre que describen la prenda («cropped», «pana», «relaxed»), sin el tipo ni
    relleno. En minúsculas y sin tildes."""
    words = set(re.findall(r"[a-z]{3,}", norm(name)))
    return {w for w in words if w not in _STOP_WORDS and w not in _TYPE_WORDS}


def price_band(cents: int) -> str:
    return next((name for limit, name in PRICE_BANDS if cents < limit), "mas_de_80")


@dataclass
class ShopTaste:
    """Me gusta / no me gusta de la tienda, por tipo, color, franja de precio y palabras del nombre:
    clave -> [neto, total]."""

    types: dict[str, list[float]] = field(default_factory=dict)
    colors: dict[str, list[float]] = field(default_factory=dict)
    prices: dict[str, list[float]] = field(default_factory=dict)
    words: dict[str, list[float]] = field(default_factory=dict)
    brands: dict[str, list[float]] = field(default_factory=dict)  # por familia: Adidas Originals es Adidas

    def learn(self, item, liked: bool, reason: str | None = None, strength: float = 1.0) -> None:
        """Un «me gusta» cuenta entero en todo (por `strength`: una compra vale varias veces más).
        Un «no me gusta» carga la culpa según el motivo (`_BLAME`)."""
        blame = (1.0, 1.0, 1.0, 1.0) if liked else _BLAME.get(reason, _BLAME[None])
        by_type, by_color, by_price, by_word = (strength * part for part in blame)
        votes = [
            (self.types, item.type, by_type),
            (self.prices, price_band(item.price_cents), by_price),
        ]
        if item.color:  # un color aún desconocido no enseña nada
            votes.append((self.colors, item.color, by_color))
        votes += [(self.words, word, by_word) for word in name_words(item.name)]
        family = brand_family(getattr(item, "brand", None))
        if family:
            votes.append((self.brands, family, by_type))  # la marca carga la misma culpa que el tipo
        for table, key, weight in votes:
            if weight:
                entry = table.setdefault(key, [0.0, 0.0])
                entry[0] += weight if liked else -weight
                entry[1] += weight

    @staticmethod
    def opinion(table: dict, key: str) -> float:
        """De -1 a 1, suavizada (con pocos votos se queda cerca de 0) y RELATIVA a lo que el usuario
        acepta en general. En una pantalla de deslizar se descarta casi todo: sin esto, todo acababa
        con «sueles descartar…» y ninguna clave destacaba sobre las demás."""
        net, total = table.get(key, (0.0, 0.0))
        if not total:
            return 0.0
        all_net = sum(entry[0] for entry in table.values())
        all_total = sum(entry[1] for entry in table.values())
        # Fracción de «me gusta» en esta tabla. Con pocas valoraciones tira hacia la mitad, para que
        # los primeros «me gusta» (o los primeros descartes) ya cuenten como preferencia.
        usual = ((all_net + all_total) / 2 + 0.5 * USUAL_PRIOR_VOTES) / (all_total + USUAL_PRIOR_VOTES)
        liked = (net + total) / 2
        rate = (liked + PREF_PRIOR_VOTES * usual) / (total + PREF_PRIOR_VOTES)
        return max(-1.0, min(1.0, 2 * (rate - usual)))


def load_shop_taste(db: Session) -> ShopTaste:
    """Cada señal con su peso (acordado con el usuario): lo que compra manda (`BOUGHT_WEIGHT`), un
    «me gusta» cuenta 1, un «me gusta» que no acabó en compra (caducó o lo quitó) cuenta la mitad
    (`LAPSED_WEIGHT`) y un descarte, casi nada (`_BLAME`). Lo caducado sin valorar no dice nada, y lo
    deshecho con «Volver» tampoco: vuelve a estar pendiente."""
    learned = ShopTaste()
    counted = or_(ShopItem.status.in_((LIKED, DISCARDED, BOUGHT, EXPIRED)), ShopItem.prev_status.is_not(None))
    for item in db.scalars(select(ShopItem).where(counted)):
        # Un «buscado» no enseña nada, y un color apartado («variante») tampoco. Si ya existía
        # (descartado, caducado…), sigue contando como lo que era: volver a buscar algo no borra lo
        # que se dijo de ello.
        status = item.prev_status if item.status in (SEARCHED, VARIANT) else item.status
        if status == BOUGHT:
            learned.learn(item, True, strength=BOUGHT_WEIGHT)
        elif status == LIKED:
            learned.learn(item, True)
        elif status not in (DISCARDED, EXPIRED):
            continue
        elif item.liked_at is not None:  # gustó, pero caducó o lo quitó sin comprarlo
            learned.learn(item, True, strength=LAPSED_WEIGHT)
        elif status == DISCARDED:
            learned.learn(item, False, item.discard_reason)
    return learned


# ---------- La nota

# tipo -> (plural, es femenino). El calzado ya va en plural.
_TYPE_FORMS = {
    "camiseta": ("camisetas", True), "camisa": ("camisas", True), "polo": ("polos", False),
    "sudadera": ("sudaderas", True), "jersey": ("jerséis", False), "sobrecamisa": ("sobrecamisas", True),
    "chaqueta": ("chaquetas", True), "abrigo": ("abrigos", False), "pantalón": ("pantalones", False),
    "vaquero": ("vaqueros", False), "chino": ("chinos", False), "pantalón corto": ("pantalones cortos", False),
    "chándal": ("chándales", False), "zapatillas": ("zapatillas", True), "zapatos": ("zapatos", False),
    "botas": ("botas", True),
}
_PLURAL_ONLY = {"zapatillas", "zapatos", "botas"}
_INVARIABLE_COLORS = {"azul marino", "verde oliva", "burdeos", "beige", "naranja", "rosa"}
# categoría -> (una, varias, «no tienes … en ese color») para «Solo tienes 2 …» y «No tienes … en blanco»
_CATEGORY_FORMS = {
    "parte_superior": ("parte de arriba", "partes de arriba", "partes de arriba"),
    "capa_exterior": ("chaqueta o abrigo", "chaquetas y abrigos", "chaquetas ni abrigos"),
    "parte_inferior": ("pantalón", "pantalones", "pantalones"),
    "calzado": ("par de zapatos", "pares de zapatos", "calzado"),
}
_PATTERN_FORMS = {
    "rayas": "de rayas", "cuadros": "de cuadros", "gráfico": "con dibujo", "logo": "con logo",
    "bloques de color": "de bloques de color",
}
_PLAIN = ("liso", "texturizado")


def _color_word(color: str, feminine: bool, plural: bool) -> str:
    """El color concordado con la prenda: «sudaderas negras», «jerséis grises», «polo azul marino»."""
    if color in _INVARIABLE_COLORS:
        return color
    word = color
    if word.endswith("o") and feminine:
        word = word[:-1] + "a"
    if plural:
        word = "marrones" if word == "marrón" else word + ("s" if word[-1] in "aeiou" else "es")
    return word


def _typed(garment_type: str, count: int, color: str | None = None) -> str:
    """«1 sudadera negra», «3 sudaderas negras», «2 pares de zapatillas blancas»."""
    plural_form, feminine = _TYPE_FORMS[garment_type]
    if garment_type in _PLURAL_ONLY:
        text = f"{count} {'par' if count == 1 else 'pares'} de {garment_type}"
        return f"{text} {_color_word(color, feminine, True)}" if color else text
    plural = count != 1
    text = f"{count} {plural_form if plural else garment_type}"
    return f"{text} {_color_word(color, feminine, plural)}" if color else text


def _none(garment_type: str, color: str | None = None) -> str:
    """«No tienes ninguna sobrecamisa», «No tienes ningún jersey verde», «No tienes botas»."""
    _plural, feminine = _TYPE_FORMS[garment_type]
    if garment_type in _PLURAL_ONLY:
        text = f"No tienes {garment_type}"
        return f"{text} {_color_word(color, feminine, True)}" if color else text
    text = f"No tienes {'ninguna' if feminine else 'ningún'} {garment_type}"
    return f"{text} {_color_word(color, feminine, False)}" if color else text


# Las palabras que dicen qué prenda es: no describen el corte, así que no se aprenden como «palabras».
_TYPE_WORDS = {norm(w) for t_, (plural, _f) in _TYPE_FORMS.items() for w in (*t_.split(), *plural.split())} | {
    "jeans", "jean", "cazadora", "parka", "bermuda", "zapatilla", "zapato", "bota", "cardigan",
}


def wardrobe_item(g: Garment) -> outfits.Item:
    return outfits.Item(
        id=g.id, type=g.type, category=g.category, color=g.color_primary, style=g.style, season=g.season,
        pattern=g.pattern, details=f"{g.name} {g.details or ''}", closure=g.closure, fit=g.fit,
        thickness=g.thickness, hood=g.hood,
    )


def candidate_item(product) -> outfits.Item:
    """Un producto de tienda (ShopProduct o ShopItem) visto como una prenda más. Su id 0 no choca con ninguna."""
    return outfits.Item(
        id=0, type=product.type, category=product.category, color=product.color, style=product.style,
        season=product.season, pattern=product.pattern, details=product.details or product.name,
    )


# Lo que delata a una prenda de verano en el nombre o en la descripción de la tienda.
# En español y en francés (Zara Francia).
_SUMMER_TEXT = re.compile(
    r"\b(tirantes|sin mangas|lino|bermudas?|shorts?|banador|sandalias?|chanclas?|"
    r"sans manches|debardeurs?|lin|maillot de bain|sandales?|claquettes?|tongs)\b"
)
_SHORT_SLEEVE = re.compile(r"\bmangas? cortas?\b|\bmanches? courtes?\b|\bshort[- ]sleeves?\b|(?<![a-z])s/s(?![a-z])")
_LONG_SLEEVE = re.compile(r"\bmangas? largas?\b|\bmanches? longues?\b|\blong[- ]?sleeves?\b|(?<![a-z])l/s(?![a-z])")


def summer_text(text: str | None) -> bool:
    """¿El texto (nombre o descripción) habla de manga corta, tirantes, lino y similares?

    Si dice a la vez manga corta y manga larga (pasa: «Camiseta manga larga» con una descripción
    copiada de la de manga corta), la manga no decide.
    """
    text = norm(text)
    if _SUMMER_TEXT.search(text):
        return True
    return bool(_SHORT_SLEEVE.search(text)) and not _LONG_SLEEVE.search(text)


def out_of_season(product, today: date) -> bool:
    """Fuera de mayo-septiembre no se propone ropa de verano: la misma regla que el outfit de Hoy, más
    lo que digan el nombre y la descripción (un jersey «de manga corta», una camisa de lino)."""
    if outfits.warm_months(today):
        return False
    return outfits.summer_only(candidate_item(product)) or summer_text(f"{product.name} {product.details or ''}")


def score(product, wardrobe: list[outfits.Item], taste=None, prefs: ShopTaste | None = None) -> tuple[float, list[dict]]:
    """La nota de un producto contra el armario (0-100) y los motivos, legibles, a favor y en contra.

    Si el color aún no se sabe ("": Courir no lo dice en el listado, llega con la ficha), lo que depende
    del color ni suma ni resta: ni gustos de color, ni paleta, ni repetidos de ese color."""
    candidate = candidate_item(product)
    known_color = bool(candidate.color)
    reasons: list[dict] = []
    total = BASE

    def reason(text: str, kind: str = "pro") -> None:
        reasons.append({"text": text, "kind": kind})

    # 1. Lo que el usuario ha ido diciendo en la tienda: lo que más pesa.
    if prefs is not None:
        plural, feminine = _TYPE_FORMS[candidate.type]
        article = "las" if feminine else "los"
        by_type = prefs.opinion(prefs.types, candidate.type)
        by_color = prefs.opinion(prefs.colors, candidate.color) if known_color else 0.0
        by_price = prefs.opinion(prefs.prices, price_band(product.price_cents))
        by_word = {w: prefs.opinion(prefs.words, w) for w in sorted(name_words(product.name))}
        total += W_PREF_TYPE * by_type + W_PREF_COLOR * by_color + W_PREF_PRICE * by_price
        total += W_PREF_WORD * max(-1.0, min(1.0, sum(by_word.values())))
        if by_type >= CLEAR_PREF:
            reason(f"Te suelen gustar {article} {plural}")
        elif by_type <= -CLEAR_PREF:
            reason(f"Sueles descartar {article} {plural}", "contra")
        if by_color >= CLEAR_PREF:
            reason(f"Te suele gustar el {candidate.color}")
        elif by_color <= -CLEAR_PREF:
            reason(f"Sueles descartar el {candidate.color}", "contra")
        if by_word:
            strongest = max(by_word, key=lambda w: abs(by_word[w]))
            if by_word[strongest] >= CLEAR_PREF:
                reason(f"Te suele gustar lo «{strongest}»")
            elif by_word[strongest] <= -CLEAR_PREF:
                reason(f"Sueles descartar lo «{strongest}»", "contra")
        family = brand_family(getattr(product, "brand", None))
        if family:
            by_brand = prefs.opinion(prefs.brands, family)
            total += W_PREF_BRAND * by_brand
            if by_brand >= CLEAR_PREF:
                reason(f"Te suelen gustar {article} {family}")
            elif by_brand <= -CLEAR_PREF:
                reason(f"Sueles descartar {article} {family}", "contra")
        if W_PREF_PRICE and by_price >= CLEAR_PREF:
            reason("Precio como los que te gustan")
        elif W_PREF_PRICE and by_price <= -CLEAR_PREF:
            reason("Sueles descartar este rango de precio", "contra")

    # 2a. Con cuántas prendas combina: las de las otras categorías, sin mezclar verano con invierno.
    others = [
        g for g in wardrobe
        if g.category != candidate.category and {g.season, candidate.season} != {"verano", "invierno"}
    ]
    matches = sum(1 for g in others if outfits.combo_affinity([candidate, g], taste) >= GOOD_PAIR)
    if others:
        total += W_MATCH * matches / len(others)
        if matches:
            reason(f"Combina con {matches} de tus prendas")
        elif len(others) >= 3:
            reason("No combina bien con lo que tienes", "contra")

    # 2b. ¿Es de los colores que ya lleva, y los lleva en esa parte del cuerpo? Lo normal es comprar en
    #     la paleta propia, y que lleve camisetas blancas no quiere decir que lleve pantalones blancos.
    in_category = [g for g in wardrobe if g.category == candidate.category]
    # Un pantalón corto no cuenta como costumbre para uno largo (ni al revés): bermuda cruda no es vaquero crudo.
    alike = [g for g in in_category if (g.type == "pantalón corto") == (candidate.type == "pantalón corto")]
    neutral = style_rules.is_neutral(candidate)
    off_category = False
    if wardrobe and known_color:
        share_all = sum(1 for g in wardrobe if g.color == candidate.color) / len(wardrobe)
        share_here = share_all
        if len(alike) >= FEW_IN_CATEGORY:
            share_here = sum(1 for g in alike if g.color == candidate.color) / len(alike)
        share = (share_all + share_here) / 2
        total += W_PALETTE * min(1.0, share / PALETTE_FULL)
        # Si ya ha dicho en la tienda que ese color le gusta, no llevarlo todavía no resta.
        accepted = prefs is not None and prefs.opinion(prefs.colors, candidate.color) > 0
        if share_all == 0 and not neutral:
            if not accepted:
                total += OFF_PALETTE
                reason(f"No llevas nada {candidate.color}", "contra")
        elif share_here == 0 and len(alike) >= HABIT_MIN:
            off_category = True
            if not accepted:
                total += OFF_CATEGORY
                reason(f"No tienes {_CATEGORY_FORMS[candidate.category][2]} en {candidate.color}", "contra")
        elif share >= 0.1:
            reason(f"Es un color que ya llevas ({candidate.color})")

    # 2c. Básico o llamativo: el estampado y el corte.
    if candidate.pattern in _PLAIN:
        if neutral:
            total += W_BASIC
    elif wardrobe and not any(g.pattern == candidate.pattern for g in wardrobe):
        total += LOUD
        reason(f"No llevas nada {_PATTERN_FORMS.get(candidate.pattern, candidate.pattern)}", "contra")
    risky = _RISKY.search(norm(product.name))
    if risky and not (prefs is not None and prefs.opinion(prefs.words, risky.group(1)) > 0):
        total += RISKY
        reason(f"Corte poco habitual ({risky.group(1)})", "contra")

    # 3. Huecos del armario y repetidos: desempate.
    same_type = [g for g in wardrobe if g.type == candidate.type]
    same = sum(1 for g in same_type if g.color == candidate.color) if known_color else 0
    if not same_type:
        total += GAP_TYPE
        reason(_none(candidate.type))
    elif same:
        total += DUPLICATE * min(same, MAX_DUPLICATES)
        reason(f"Ya tienes {_typed(candidate.type, same, candidate.color)}", "contra")
    elif neutral and not off_category:
        # Solo un color base es un hueco de verdad. «No tienes ningún jersey rosa» no es motivo para comprarlo.
        total += GAP_COLOR
        reason(_none(candidate.type, candidate.color))
    if len(in_category) < FEW_IN_CATEGORY:
        total += GAP_CATEGORY
        if in_category:
            one, many, _in = _CATEGORY_FORMS[candidate.category]
            reason(f"Solo tienes {len(in_category)} {one if len(in_category) == 1 else many}")

    return round(max(0.0, min(100.0, total)), 1), reasons


@dataclass
class Context:
    """Lo que hace falta para puntuar: el armario, lo aprendido en Gustos y lo aprendido en la tienda."""

    wardrobe: list[outfits.Item]
    taste: object
    prefs: ShopTaste

    @classmethod
    def load(cls, db: Session) -> "Context":
        from ..routers.taste import load_taste  # aquí, para no atar el servicio a los routers al importar

        return cls(
            wardrobe=[wardrobe_item(g) for g in db.scalars(select(Garment))],
            taste=load_taste(db),
            prefs=load_shop_taste(db),
        )

    def score(self, product) -> tuple[float, list[dict]]:
        return score(product, self.wardrobe, self.taste, self.prefs)


def rescore_pending(db: Session) -> None:
    """Vuelve a puntuar lo que queda por ver: cada me gusta / no me gusta cambia el orden de lo siguiente."""
    pending = list(db.scalars(select(ShopItem).where(ShopItem.status == NEW)))
    if not pending:
        return
    context = Context.load(db)
    for item in pending:
        item.score, item.reasons = context.score(item)
    db.commit()


# ---------- Estados


def _drop_photos(item: ShopItem) -> None:
    for photo_id in item.photos or []:
        storage.delete(photo_id)
    item.photos = []


def _retire(item: ShopItem, status: str) -> None:
    """Deja de enseñarse para siempre: se queda la fila (para no volver a proponerlo) y se borran sus fotos."""
    _drop_photos(item)
    item.status = status
    item.can_undo = False


def expire_old(db: Session, now: datetime | None = None) -> int:
    """Caduca los «me gusta» que ya cumplieron su plazo. No pregunta a la tienda."""
    now = now or now_utc()
    expired = 0
    for item in db.scalars(select(ShopItem).where(ShopItem.status == LIKED)):
        if _aware(item.expires_at) and _aware(item.expires_at) <= now:
            _retire(item, EXPIRED)
            expired += 1
    if expired:
        db.commit()
    return expired


def _retire_unseen(item: ShopItem) -> None:
    """Se acabó su tanda sin que se valorase: caduca. Si antes de volver a traerlo ya se había dicho
    algo de él (descartado, caducado…), vuelve a ser eso."""
    _retire(item, item.prev_status or EXPIRED)
    item.prev_status = None


def like(db: Session, item: ShopItem) -> None:
    """A «Me gustan», con su caducidad. Vale para una propuesta de Descubrir, para un «buscado» y para
    un color visto desde otro (el «me gusta» es al color que se está viendo)."""
    now = now_utc()
    # «Volver» es cosa de Descubrir: lo que entra por el buscador no pasa por ahí.
    item.can_undo = item.status == NEW
    item.status = LIKED
    item.prev_status = item.discard_reason = None
    item.liked_at = item.decided_at = now
    item.expires_at = now + timedelta(days=LIKED_DAYS)
    db.commit()
    rescore_pending(db)
    if not _has_photos(item):
        photos_soon()  # guardado sin foto (desde el buscador): se baja en segundo plano
    top_up_soon()  # quedan menos por ver: se repone la reserva en segundo plano


def dislike(db: Session, item: ShopItem) -> None:
    """No se vuelve a proponer. Las fotos se quedan mientras se pueda deshacer con «Volver»: se borran
    en la siguiente consulta semanal de su tienda (`_close_undo`)."""
    item.status = DISCARDED
    item.decided_at = now_utc()
    item.discard_reason = None
    item.can_undo = True
    db.commit()
    rescore_pending(db)
    top_up_soon()


def set_reason(db: Session, item: ShopItem, reason: str | None) -> None:
    """Por qué se descartó: decide a qué se le carga la culpa al aprender (`_BLAME`)."""
    item.discard_reason = reason
    db.commit()
    rescore_pending(db)


def last_decision(db: Session) -> ShopItem | None:
    """El último me gusta / no me gusta que aún se puede deshacer, de las tiendas activadas."""
    return db.scalars(
        select(ShopItem)
        .where(ShopItem.can_undo.is_(True), ShopItem.status.in_((LIKED, DISCARDED)),
               ShopItem.store.in_(enabled_stores(db)))
        .order_by(ShopItem.decided_at.desc(), ShopItem.id.desc())
        .limit(1)
    ).first()


def undo(db: Session) -> ShopItem | None:
    """«Volver»: deshace la última decisión y la deja otra vez pendiente, como si no se hubiera valorado
    (no cuenta al aprender y, si era un «me gusta», sale de Me gustan). None si no hay nada que deshacer."""
    item = last_decision(db)
    if item is None:
        return None
    item.status = NEW
    item.liked_at = item.expires_at = item.decided_at = item.discard_reason = None
    item.can_undo = False
    db.commit()
    rescore_pending(db)
    return item


def _close_undo(db: Session, store: str) -> None:
    """Con la consulta semanal se cierra la tanda: sus decisiones ya no se pueden deshacer y lo
    descartado suelta las fotos que guardaba por si acaso."""
    for item in db.scalars(select(ShopItem).where(ShopItem.store == store, ShopItem.can_undo.is_(True))):
        item.can_undo = False
        if item.status == DISCARDED:
            _drop_photos(item)
    db.commit()


def remove_liked(db: Session, item: ShopItem) -> None:
    _retire(item, DISCARDED)
    item.decided_at = now_utc()
    db.commit()


def expires_soon(item: ShopItem, now: datetime | None = None) -> bool:
    expires = _aware(item.expires_at)
    return bool(expires and expires - (now or now_utc()) <= timedelta(days=EXPIRES_SOON_DAYS))


# ---------- «La he comprado»


def _model_used(provider: str | None) -> str | None:
    """«modelo · esfuerzo» con el que Codex analizó, igual que al añadir una prenda a mano."""
    if provider != "codex":
        return None
    model, effort = codex_models.chosen()
    return " · ".join(part for part in (model or "automático", effort) if part)


class CannotBuy(Exception):
    pass


def store_reference(item: ShopItem) -> str | None:
    """La referencia como la escribe la tienda («3918/300/800»), o None si el conector no sabe darla."""
    make = getattr(shops.CONNECTORS.get(item.store), "reference", None)
    try:
        value = make(item.store_data or {}) if make else None
    except Exception:  # un `store_data` antiguo o raro no puede tumbar la ficha
        return None
    return str(value)[:40] if value else None


def colors_of(item: ShopItem) -> list[dict] | None:
    """Los colores del producto, para la interfaz: [{"product_ref", "name", "hex", "current",
    "available", "url"}]. Vacío si solo existe en uno; None si aún no se sabe (item guardado antes de
    que se apuntaran: `ensure_colors` lo rellena).

    `available`: se puede ver ya. En las tiendas que no pueden traer un color al momento (JD Sports, con
    navegador: `prepared_colors`) solo los ya preparados (ver `prepare_colors`); los demás se enseñan
    apagados, con el enlace a la tienda, y van detrás de los disponibles. En el resto, todos."""
    if item.siblings is None:
        return None
    siblings = family_of(item)
    if len(siblings) < 2:
        return []
    ready: set[str] | None = None
    if getattr(shops.CONNECTORS.get(item.store), "prepared_colors", False):
        db = object_session(item)
        others = [s["product_ref"] for s in siblings if s.get("product_ref") != item.product_ref]
        ready = set()
        if db is not None and others:
            ready = {row.product_ref for row in db.scalars(select(ShopItem).where(ShopItem.product_ref.in_(others)))
                     if _color_ready(db, row)}
    foreign = _foreign(item.store, item.url)
    colors = [
        {
            "product_ref": sibling["product_ref"],
            "name": color_name(sibling.get("name"), sibling.get("name_es"), foreign),
            # Sin tono de la tienda, el de nuestra paleta que mejor le va al nombre.
            "hex": sibling.get("hex") or catalog.COLOR_HEX.get(estimate_color(sibling.get("name")), UNKNOWN_HEX),
            "current": sibling["product_ref"] == item.product_ref,
            "available": ready is None or sibling["product_ref"] == item.product_ref or sibling["product_ref"] in ready,
            "url": sibling.get("url") or item.url,
        }
        for sibling in sorted(siblings, key=lambda sibling: sibling["product_ref"])
    ]
    return sorted(colors, key=lambda color: not color["available"])  # estable: el orden de siempre dentro


def color_name(store_color: str | None, translated: str | None, foreign: bool, palette: str | None = None) -> str:
    """El nombre de un color para enseñarlo: el traducido si lo hay; si la tienda no está en español y
    aún no ha llegado la traducción, el de nuestra paleta («negro»), nunca el original («Noir»)."""
    if translated:
        return translated
    if foreign and store_color:
        return palette or estimate_color(store_color)
    return store_color or ""


def shown_color(item: ShopItem) -> str:
    """El color de un producto como se enseña (tarjeta, visor, Me gustan)."""
    return color_name(item.store_color, item.store_color_es, _foreign(item.store, item.url), item.color)


def _detail_color(row: ShopItem, detail) -> None:
    """El color de la ficha cuando el listado no lo traía (Courir), y lo que la ficha sabe para la
    referencia (el código de fabricante)."""
    if getattr(detail, "store_color", "") and not row.store_color:
        row.store_color = detail.store_color[:60]
        row.color = estimate_color(detail.store_color, detail.color_hex)
        row.store_color_es = None
        row.translated = None
    extra = getattr(detail, "store_data", None) or {}
    if extra:
        row.store_data = {**(row.store_data or {}), **{k: v for k, v in extra.items() if v}}
    _note_code(row)


def _note_code(row: ShopItem) -> None:
    """Apunta el código de fabricante (como clave) si la tienda lo dice: ver `also_in` y `_promote`."""
    row.maker_code = shops.maker_code(row.store, row.store_data or {})


# ---------- La familia de colores de un producto
#
# La familia son los colores de LA MISMA prenda: mismo modelo, mismo nombre, otro color. Cada color es
# un item aparte y cada item guarda la familia entera (`siblings`), él incluido. Reglas:
# - Lo dice la tienda en la ficha del producto, y de lo que enlaza solo vale lo que es el mismo modelo
#   (`same_model` del conector: Courir enlaza como «colores» toda la línea, hasta 41 productos).
# - Elegir un color no cambia los circulitos: los dos items, el que se deja y el que se elige, se
#   quedan con la misma familia (la unión de lo que sabía cada uno), así que volver atrás enseña lo mismo.
# - Al releer una ficha manda la tienda (un color retirado desaparece), salvo en las tiendas donde cada
#   ficha nombra solo a algunos de sus colores (`partial_colors`): ahí lo ya conocido se conserva.
# - Un color que la tienda ya no tiene se quita de la familia en cuanto se comprueba (`_forget_color`).
# Nunca se unen familias de productos distintos: sin el filtro del modelo la unión acaba siendo la
# línea entera.


def _same_model(store: str, url: str | None, own_ref: str | None, siblings: list[dict] | None) -> list[dict]:
    """De una lista de colores hermanos, los que son el mismo modelo que el producto de `url`. Las
    tiendas cuyo conector no dice nada (`same_model`) solo enlazan colores de verdad: todos."""
    siblings = [s for s in siblings or [] if isinstance(s, dict) and s.get("product_ref")]
    check = getattr(shops.CONNECTORS.get(store), "same_model", None)
    if check is None:
        return siblings
    return [s for s in siblings if s["product_ref"] == own_ref or check(url, s.get("url"))]


def family_of(item: ShopItem) -> list[dict]:
    """Los colores de un item, él incluido: lo guardado, sin lo que no es el mismo modelo (las listas
    guardadas antes de filtrar, que en Courir mezclaban la línea entera, se arreglan aquí al leerlas)."""
    return _same_model(item.store, item.url, item.product_ref, item.siblings)


def _own_sibling(row: ShopItem) -> dict:
    """Un item visto como color de su familia, para cuando la lista de la tienda no lo nombra."""
    return {
        "product_ref": row.product_ref, "name": row.store_color or "", "hex": row.store_color_hex,
        "url": row.url, "store_data": dict(row.store_data or {}),
        **({"name_es": row.store_color_es} if row.store_color_es else {}),
    }


def _merge_siblings(known: list[dict] | None, more: list[dict] | None) -> list[dict]:
    """Los colores de `known` más los de `more` que falten, siempre en el mismo orden. Manda `known`
    (lo más reciente que dijo la tienda de cada color), pero la traducción del nombre no se pierde."""
    merged = {s["product_ref"]: s for s in more or [] if s.get("product_ref")}
    for sibling in known or []:
        ref = sibling.get("product_ref")
        if not ref:
            continue
        before = merged.get(ref)
        if before and before.get("name_es") and not sibling.get("name_es") and before.get("name") == sibling.get("name"):
            sibling = {**sibling, "name_es": before["name_es"]}
        merged[ref] = sibling
    return sorted(merged.values(), key=lambda sibling: sibling["product_ref"])


def _share_family(item: ShopItem, target: ShopItem) -> None:
    """Al pasar de un color a otro, los dos se quedan con la misma familia: la unión de lo que sabía
    cada uno (solo del mismo modelo), con los dos dentro. Así los circulitos no cambian al tocar uno
    ni al volver, aunque la ficha de uno nombre menos colores que la del otro."""
    family = _merge_siblings(family_of(target), family_of(item))
    family = _same_model(item.store, item.url, item.product_ref, family)
    present = {s["product_ref"] for s in family}
    # El que se ve y el que se deja, siempre: sin ellos no se podría volver.
    family = _merge_siblings(family, [_own_sibling(row) for row in (item, target) if row.product_ref not in present])
    for row in (item, target):
        if row.siblings != family:
            row.siblings = [dict(s) for s in family]


def _forget_color(db: Session, item: ShopItem, product_ref: str) -> None:
    """Ese color ya no existe en la tienda (o no tiene foto de producto): se quita de la familia de
    todos los items que lo nombraban, para que el circulito no siga ahí dando el mismo error."""
    rows = db.scalars(select(ShopItem).where(ShopItem.store == item.store, ShopItem.siblings.is_not(None)))
    for row in rows:
        if row.product_ref != product_ref and any(s.get("product_ref") == product_ref for s in row.siblings or []):
            row.siblings = [s for s in row.siblings if s.get("product_ref") != product_ref]
    db.commit()


def _set_price(row: ShopItem, price: int | None, old: int | None, known: bool) -> None:
    """El precio de ahora y, si la TIENDA dice que está rebajado, el de antes (`old_price_cents`, tachado).
    Nunca se deduce comparando con lo apuntado otro día. `known`: esta fuente (listado o ficha) sabe decir si
    hay rebaja; entonces manda, y un None es que la oferta ha terminado. Si no lo sabe (la ficha de Courir
    solo da el precio de ahora), la rebaja que dijo otra fuente se conserva mientras el precio sea el mismo.
    Sin precio (una ficha sacada de lo que guardó el listado), no se toca nada."""
    if not price:
        return
    if known:
        row.old_price_cents = shops.old_price(price, old)
    elif row.price_cents != price or not shops.old_price(price, row.old_price_cents):
        row.old_price_cents = None
    row.price_cents = price


def _price_from(row: ShopItem, source) -> None:
    """El precio de un producto del listado o de una ficha (ShopProduct o ShopDetail), con su rebaja."""
    _set_price(row, source.price_cents, getattr(source, "old_price_cents", None),
               bool(getattr(source, "old_price_known", False)))


def _apply_detail(row: ShopItem, detail) -> None:
    """Lo que la ficha dice además de fotos y tallas: en qué colores existe y de qué está hecha."""
    # Siempre en el mismo orden (la tienda pone primero el color que se le pide): si no, al cambiar de
    # color los circulitos bailarían de sitio.
    # El nombre traducido de cada color se conserva mientras la tienda lo siga llamando igual.
    translated = {s["product_ref"]: s for s in row.siblings or [] if s.get("name_es")}
    siblings = []
    for sibling in detail.siblings or []:
        if not sibling.get("product_ref"):
            continue
        sibling = dict(sibling)
        before = translated.get(sibling["product_ref"])
        if before and before.get("name") == sibling.get("name"):
            sibling["name_es"] = before["name_es"]
        siblings.append(sibling)
    siblings = _same_model(row.store, row.url, row.product_ref, siblings)
    if getattr(shops.CONNECTORS.get(row.store), "partial_colors", False):
        # Donde cada ficha solo enlaza a algunos de sus colores (Courir: la gris a cuatro, la beige solo
        # a la gris), los que ya se conocían y esta ficha no nombra se conservan. En el resto manda la
        # ficha: un color que la tienda ha retirado deja de ofrecerse.
        siblings = _merge_siblings(siblings, family_of(row))
    row.siblings = sorted(siblings, key=lambda sibling: sibling["product_ref"])
    row.composition = " ".join((detail.composition or "").split())[:COMPOSITION_MAX] or None


def buy(
    db: Session, item: ShopItem, size: str | None, preferred_provider: str, ordered: bool = False
) -> tuple[Garment, bool]:
    """Pasa el producto al armario con las fotos de la tienda. Devuelve la prenda y si la analizó la IA.

    Con `ordered` la prenda entra como pedida (aún no ha llegado): Hoy y Gustos no la proponen hasta
    que se marque como recibida.

    Es el único momento en que se usa la IA: el mismo análisis que al añadir una prenda a mano. Si falla,
    la prenda se crea igualmente con los campos estimados sin IA.
    """
    photos = [p for p in (item.photos or []) if storage.exists(p)]
    if not photos:
        raise CannotBuy("Las fotos de este producto ya no están; no se puede pasar al armario")
    # De un «buscado» puede que ya tenga la prenda en casa: vale cualquier talla que exista, quede o no.
    in_stock = [s["name"] for s in item.sizes or [] if s.get("in_stock") or item.status in (SEARCHED, VARIANT)]
    if size and in_stock and size not in in_stock:
        raise CannotBuy("Esa talla no está entre las disponibles")
    front, back, extra = (photos + [None, None])[:3]
    for photo_id in photos[3:]:  # una cuarta foto (la suela en Courir) solo se veía en el visor
        storage.delete(photo_id)

    result = ai.analyze(
        [storage.photo_path(p) for p in photos[:3]],
        preferred=preferred_provider,
        prompt=build_prompt(
            has_back=bool(back), has_label=False, has_extra=bool(extra),
            kind="calzado" if item.category == "calzado" else "ropa",
        ),
    )
    store_name = shops.CONNECTORS[item.store].name if item.store in shops.CONNECTORS else item.store.capitalize()
    # En una tienda de varias marcas (Courir, JD Sports) la marca es la del producto; en Zara, Zara.
    brand = item.brand or store_name
    draft = result.draft
    if draft is not None:
        # La marca y la talla no salen de la foto: son la del producto (o la tienda) y la talla elegida.
        saved_draft = {**draft.model_dump(), "brand": brand, "size": size}
        fields = dict(
            name=draft.name.strip(), type=draft.type, color_primary=draft.color_primary.name,
            color_primary_hex=draft.color_primary.hex.lower(),
            colors_secondary=[c.model_dump() for c in draft.colors_secondary],
            pattern=draft.pattern, style=draft.style, closure=draft.closure, hood=draft.hood, fit=draft.fit,
            thickness=draft.thickness, details=draft.details.strip(), season=draft.season,
            notes=draft.notes.strip(), ai_provider=result.provider, ai_confidence=draft.confidence,
            ai_model=_model_used(result.provider),
            ai_draft=saved_draft,
        )
    else:
        saved_draft = None
        fields = dict(
            # Un color que nunca se llegó a saber: «multicolor», el único de la paleta que no dice nada.
            name=item.name[:120], type=item.type, color_primary=item.color or "multicolor",
            color_primary_hex=item.store_color_hex or catalog.COLOR_HEX[item.color or "multicolor"], colors_secondary=[],
            pattern=item.pattern, style=item.style, details="", season=item.season, notes="",
        )

    garment = Garment(
        **fields,
        category=catalog.category_of(fields["type"]),
        brand=brand,
        size=size,
        # De dónde vino, para poder buscarla o pedirla otra vez desde la Ficha.
        reference=store_reference(item),
        store_name=store_name[:40],
        store_url=item.url or None,
        on_order=ordered,
        ordered_at=now_utc() if ordered else None,
        photo_front=front,
        photo_back=back,
        photo_extra=extra,
        photo_front_original=storage.original_name(front),
        photo_back_original=storage.original_name(back) if back else None,
        photo_extra_original=storage.original_name(extra) if extra else None,
    )
    db.add(garment)
    db.flush()
    item.status = BOUGHT
    item.prev_status = None
    item.garment_id = garment.id
    item.liked_at = item.liked_at or now_utc()
    item.can_undo = False
    item.ai_draft = saved_draft
    item.photos = []  # las fotos pasan a ser de la prenda: una foto, un solo dueño
    db.commit()
    rescore_pending(db)  # el armario ha cambiado: lo que era un hueco ya no lo es
    return garment, draft is not None


# ---------- Candidatos y tandas


def _save_photos(connector, urls: list[str]) -> list[str]:
    """Baja las fotos y las guarda como las del armario. Sin la principal no hay propuesta."""
    ids: list[str] = []
    try:
        for index, url in enumerate(urls):
            try:
                ids.append(storage.save_upload(connector.download(url), f"{connector.key}.jpg"))
            except (ShopError, storage.InvalidPhoto):
                if index == 0:
                    raise
    except (ShopError, storage.InvalidPhoto) as exc:
        for photo_id in ids:
            storage.delete(photo_id)
        raise ShopError(f"sin foto principal: {exc}") from exc
    return ids


def _round_robin(queues: list[list]):
    """Reparte entre tiendas: la mejor de cada una, luego la segunda de cada una… Si una se acaba,
    siguen las demás."""
    queues = sorted((q for q in queues if q), key=lambda q: -q[0][0])
    for position in range(max((len(q) for q in queues), default=0)):
        for queue in queues:
            if position < len(queue):
                yield queue[position]


_MODEL_SKIP = _STOP_WORDS | {"homme", "hombre", "unisex", "unisexe", "mixte", "pour", "with", "and"}


def model_keys(row) -> tuple[str, str]:
    """(modelo, familia) de un producto, por su nombre, para no amontonar lo mismo en una tanda. Sin
    marca: el modelo son las tres primeras palabras que cuentan y la familia, las dos primeras
    («pantalon chino slim» / «pantalon chino»). Con marca: la marca y dos palabras / la marca y una
    («nike air force» para «Air Force 1 '07» y «Air Force 1 Low» / «nike air»). Sin palabras que
    cuenten, vacíos (no se compara)."""
    colour = set(re.findall(r"[a-z0-9]+", norm(getattr(row, "store_color", "") or "")))
    words = [
        w for w in re.findall(r"[a-z0-9]+", norm(row.name))
        if w not in _MODEL_SKIP and w not in colour and (len(w) >= 3 or any(ch.isdigit() for ch in w))
    ]
    brand = brand_family(getattr(row, "brand", None)) or ""
    brand = norm(brand)
    words = [w for w in words if w not in brand.split()]
    if not words:
        return "", ""
    # Con marca (zapatillas), el modelo son sus dos primeras palabras («Boston Suede», «Boston Birkoflor»
    # son el mismo zueco; «Air Force 1 Low» y «'07» la misma zapatilla) y la familia, la primera.
    size = 2 if brand else 3
    head = " ".join([brand, *words[:size]]).strip()
    family = " ".join([brand, *words[: size - 1]]).strip() if len(words) >= size - 1 and (brand or len(words) >= 2) else ""
    return head, family


# Al elegir qué candidatos se traen, cada repetido baja (solo para elegir) a los que quedan iguales:
TYPE_STEP = 1.5  # por cada uno ya elegido del mismo tipo de prenda (que no salgan 40 pantalones)
MODEL_STEP = 12.0  # por cada uno ya elegido del mismo modelo (el mismo nombre en otro color, 8 Air Force 1)
BRAND_STEP = 4.0  # por cada uno ya elegido de la misma marca (en las tiendas de varias marcas)
FAMILY_STEP = 10.0  # por cada uno ya elegido de la misma familia (casi el mismo nombre, el mismo modelo de una marca)


class _Variety:
    """Lo ya elegido (o ya pendiente de ver), para que lo siguiente no repita tipo, color, sección ni modelo."""

    def __init__(self, rows=()):
        self.counts: dict[tuple, int] = {}
        for row in rows:
            self.add(row)

    def _keys(self, row) -> list[tuple]:
        model, family = model_keys(row)
        keys = [("tc", row.type, row.color), ("t", row.type), ("s", row.store, row.section)]
        if model:
            keys.append(("m", model))
        if family:
            keys.append(("f", family))
        brand = brand_family(getattr(row, "brand", None))
        if brand:
            keys.append(("b", brand))
        return keys

    def add(self, row) -> None:
        for key in self._keys(row):
            self.counts[key] = self.counts.get(key, 0) + 1

    def penalty(self, row) -> float:
        steps = {"tc": REPEAT_STEP, "t": TYPE_STEP, "s": SECTION_STEP, "m": MODEL_STEP, "f": FAMILY_STEP,
                 "b": BRAND_STEP}
        return sum(steps[key[0]] * self.counts.get(key, 0) for key in self._keys(row))


def _varied(entries: list[tuple], head: int, variety: "_Variety | None" = None) -> list[tuple]:
    """Ordena por nota, pero sin amontonar lo mismo: cada elegido baja un poco (solo para elegir) a los
    que quedan de su mismo tipo y color, de su mismo tipo, de su misma categoría de la tienda y, sobre
    todo, de su mismo modelo (ver `model_keys`). Así una categoría floja no entra a la fuerza y una
    buena no lo llena todo. Solo se afina la cabeza (`head`): el resto va por nota. `variety` trae lo
    que ya está pendiente de ver, para que una reposición no repita lo que ya hay en la cola.

    Con miles de candidatos solo se miran los mejores (cinco veces la cabeza, y al menos 200): lo que
    queda por debajo no llegaría a entrar aunque los de arriba se penalizaran.
    """
    ordered = sorted(entries, key=lambda entry: (-entry[0], entry[2].product_ref))
    # Los mejores en general y, además, los mejores de cada tipo de prenda: si no, con mil pantalones
    # empatados arriba no entraría nada más a competir.
    pool_size = max(200, head * 5)
    chosen, by_type = set(range(min(pool_size, len(ordered)))), {}
    for index, entry in enumerate(ordered):
        seen = by_type.setdefault(entry[2].type, 0)
        if seen < head:
            chosen.add(index)
            by_type[entry[2].type] = seen + 1
    left = [entry for index, entry in enumerate(ordered) if index in chosen]
    rest = [entry for index, entry in enumerate(ordered) if index not in chosen]
    picked: list[tuple] = []
    variety = variety or _Variety()
    while left and len(picked) < head:
        best = max(range(len(left)), key=lambda i: (left[i][0] - variety.penalty(left[i][2]), -i))
        entry = left.pop(best)
        variety.add(entry[2])
        picked.append(entry)
    return picked + left + rest


def _ranked(context: "Context", rows: list[ShopItem], head: int, variety_rows=()) -> list[tuple]:
    """Los candidatos en el orden en que se intentará traerlos, como (nota, motivos, fila).

    El cupo se reparte a partes iguales entre tiendas, para que un catálogo grande no entierre a los
    demás, y dentro de cada tienda manda la nota con algo de variedad (`_varied`). Es el orden de
    traída: al enseñarlas, las propuestas van por nota, vengan de la tienda que vengan.
    `variety_rows`: lo que ya está pendiente de ver (una reposición no debe repetirlo).
    """
    by_store: dict[str, list[tuple]] = {}
    for row in rows:
        value, reasons = context.score(row)
        by_store.setdefault(row.store, []).append((value, reasons, row))
    pending = list(variety_rows)
    return list(_round_robin([
        _varied(entries, head, _Variety([r for r in pending if r.store == store]))
        for store, entries in by_store.items()
    ]))


def _store_candidate(db: Session, row: ShopItem | None, product, today: date) -> ShopItem:
    """Guarda (o pone al día) un producto del catálogo como candidato: todo lo del listado, sin fotos."""
    name = product.name[:160]
    if row is None:
        row = ShopItem(
            store=product.store, product_ref=product.product_ref, status=CANDIDATE, batch=today, photos=[],
            sizes=[], reasons=[], score=0.0, first_seen_at=now_utc(), details="",
        )
        db.add(row)
    # Si ya se le bajó la ficha, se conserva lo que decía la descripción (y la temporada que salió de
    # ella): así un «manga corta» ya descubierto no vuelve a gastar una petición cada semana.
    described = row.name == name and len(row.details or "") > len(product.details)
    if row.name != name or row.store_color != product.store_color[:60]:
        row.name_es = row.store_color_es = None  # lo traducido era de otro texto
        row.translated = None
    row.name, row.url = name, product.url
    _price_from(row, product)
    row.brand = (getattr(product, "brand", "") or "")[:40] or None
    # Lo que solo dice la ficha (el código de fabricante en Snipes, size? y Foot Locker) no se pierde
    # porque el listado de la semana siguiente no lo traiga.
    learnt = {k: v for k, v in (row.store_data or {}).items() if k == "mpn" and v and not product.store_data.get(k)}
    row.store_color, row.section = product.store_color[:60], product.section
    row.store_data = {**product.store_data, **learnt}
    _note_code(row)
    row.type, row.category, row.color = product.type, product.category, product.color
    row.pattern, row.style = product.pattern, product.style
    if not described:
        row.season, row.details = product.season, product.details
    row.last_checked_at = None  # todavía no se le ha pedido la ficha esta semana
    row.listed_at = now_utc()
    return row


# ---------- El filtro de Descubrir


@dataclass(frozen=True)
class ShopFilter:
    """Lo que el usuario ha elegido en «Filtros» (20-11-2026). Vacío = todo.

    - `stores`: una o varias tiendas.
    - `categories` y `types`: partes del cuerpo y tipos concretos. Se suman: «Pantalones» + «sudadera»
      enseña los pantalones y las sudaderas.
    - `colors`: el color principal (nuestra paleta).
    - `max_price`: hasta ese precio, en céntimos. `sale`: solo lo que la tienda dice que está rebajado.
    """

    stores: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    types: tuple[str, ...] = ()
    colors: tuple[str, ...] = ()
    max_price: int | None = None
    sale: bool = False

    @classmethod
    def of(cls, store: str | None = None, category: str | None = None) -> "ShopFilter":
        return cls(stores=(store,) if store else (), categories=(category,) if category else ())

    @property
    def empty(self) -> bool:
        return not (self.stores or self.categories or self.types or self.colors or self.max_price or self.sale)

    def as_dict(self) -> dict:
        return {"stores": list(self.stores), "categories": list(self.categories), "types": list(self.types),
                "colors": list(self.colors), "max_price": self.max_price, "sale": self.sale}

    def apply(self, stmt):
        """Las condiciones que no son de tienda, en SQL (la tienda se mira con las activadas)."""
        if self.categories or self.types:
            kinds = []
            if self.categories:
                kinds.append(ShopItem.category.in_(self.categories))
            if self.types:
                kinds.append(ShopItem.type.in_(self.types))
            stmt = stmt.where(or_(*kinds))
        if self.colors:
            stmt = stmt.where(ShopItem.color.in_(self.colors))
        if self.max_price is not None:
            stmt = stmt.where(ShopItem.price_cents <= self.max_price)
        if self.sale:
            stmt = stmt.where(ShopItem.old_price_cents.is_not(None), ShopItem.old_price_cents > ShopItem.price_cents)
        return stmt

    def store_ok(self, store: str) -> bool:
        return not self.stores or store in self.stores

    def matches(self, row) -> bool:
        if not self.store_ok(row.store):
            return False
        if (self.categories or self.types) and row.category not in self.categories and row.type not in self.types:
            return False
        if self.colors and row.color not in self.colors:
            return False
        if self.max_price is not None and (row.price_cents or 0) > self.max_price:
            return False
        if self.sale and not (row.old_price_cents and row.old_price_cents > (row.price_cents or 0)):
            return False
        return True


def candidates_left(db: Session, today: date | None = None, store: str | None = None,
                    category: str | None = None, only: ShopFilter | None = None) -> list[ShopItem]:
    """Los candidatos que «Ver más» aún puede traer: de las tiendas activadas (o de las del filtro), con
    el filtro de Descubrir, de temporada y sin haber fallado ya esta semana al pedir su ficha."""
    today = today or outfits.local_today()
    only = only or ShopFilter.of(store, category)
    stores = [s for s in enabled_stores(db) if only.store_ok(s) and reachable(db, s, today)]
    stmt = select(ShopItem).where(
        ShopItem.status == CANDIDATE, ShopItem.store.in_(stores), ShopItem.last_checked_at.is_(None)
    )
    stmt = only.apply(stmt)
    return [row for row in db.scalars(stmt) if not out_of_season(row, today)]


def _detail_for(row, offline: bool = False):
    """La ficha de un candidato: la que guardó el listado si la tienda la deja (sin volver a la web), y
    si no, la de la tienda. `offline`: en las tiendas de navegador, solo la guardada (None si no hay)."""
    detail = shops.cached_detail(row.store, row.store_data or {})
    if detail is not None:
        return detail
    if offline and shops.needs_browser(row.store):
        return None
    return shops.CONNECTORS[row.store].detail(row.store_data)


def _promote(db: Session, context: "Context", ranked: list[tuple], limit: int, today: date, failed,
             offline: bool = False, stop=None, on_step=None) -> list[float]:
    """Baja la ficha y las fotos de los mejores candidatos hasta tener `limit` propuestas nuevas, y
    devuelve sus notas. Si uno no sirve (ya no existe, sin foto, sin tallas o, leída la descripción,
    fuera de temporada) entra el siguiente, con un tope de peticiones por educación con la tienda.

    La ficha sale, si se puede, de lo que guardó el listado (Pull&Bear, Bershka, JD Sports): así no se
    abre el navegador para nada y solo se bajan las fotos de su CDN. Con `offline` (la reserva, de día)
    las tiendas de navegador que no guardaron nada se saltan. `stop()` dice si hay que parar (cancelada).

    La misma zapatilla (mismo código de fabricante: modelo y color) puede estar en varias tiendas
    (Courir, Snipes, size?, Foot Locker, Nike): solo se propone una, la de mejor nota (a igualdad, la más
    barata). Si la de otra tienda ya está pendiente de ver y esta sale mejor, la otra vuelve a candidata
    y se queda esta; si ya se dijo algo de ella (me gusta, descartada, comprada), no se propone. Si el
    código solo se sabe con la ficha (Snipes, size?, Foot Locker), se mira al leerla.
    """
    promoted: dict[str, float] = {}  # product_ref -> nota de lo traído en esta vuelta
    attempts = 0
    # La misma prenda no se enseña dos veces en dos colores: lo que ya se ve en esta tanda (pendiente,
    # apartado o recién decidido) y sus colores hermanos no entran como propuesta aparte.
    shown, family = _shown_this_round(db)
    taken = _taken_codes(db)  # código de fabricante -> la fila que ya lo enseña (o lo decidió)
    best = _best_by_code(ranked)  # código de fabricante -> la mejor de las candidatas con ese código
    stopped: set[str] = set()  # tiendas que han bloqueado o cuyo navegador no arranca: ni una petición más
    for value, _reasons, row in ranked:
        if len(promoted) >= limit or attempts >= limit * 2:
            break
        if stop is not None and stop():
            break
        if row.store in stopped:
            continue
        if row.product_ref in family:
            row.last_checked_at = now_utc()  # esta semana ya no se intenta: sale como color de otra
            db.commit()
            continue
        if row.maker_code and (best.get(row.maker_code, row.product_ref) != row.product_ref or (
                row.maker_code in taken and not _beats(value, row, taken[row.maker_code]))):
            continue  # la misma zapatilla ya se enseña (o se decidió), o la de otra tienda sale mejor
        connector = shops.CONNECTORS[row.store]
        attempts += 1
        if on_step is not None and attempts <= limit:
            on_step()
        try:
            detail = _detail_for(row, offline)
            if detail is None and offline and shops.needs_browser(row.store):
                attempts -= 1
                continue  # sin lo del listado no se abre el navegador de día: ya llegará de noche
            row.last_checked_at = now_utc()
            if detail is None or not detail.photo_urls or not detail.in_stock:
                db.commit()
                continue  # ya no existe, no tiene foto de producto o no queda ninguna talla
            siblings = {
                s["product_ref"] for s in _same_model(row.store, row.url, row.product_ref, detail.siblings)
            } - {row.product_ref}
            if siblings & shown:
                db.commit()
                continue  # es otro color de algo que ya se está enseñando (y de lo que no se sabían los colores)
            code = shops.maker_code(row.store, {**(row.store_data or {}), **(detail.store_data or {})})
            rival = taken.get(code) if code else None
            if rival is not None and rival.product_ref != row.product_ref:
                if _beats(value, row, rival):
                    _swap_out(rival)  # pendiente de ver, pero esta sale mejor: se queda esta
                    promoted.pop(rival.product_ref, None)
                    shown.discard(rival.product_ref)
                else:
                    row.maker_code = code
                    db.commit()
                    continue  # la misma zapatilla ya se enseña (de otra tienda)
            description = " ".join((detail.description or "").split())[:DESCRIPTION_MAX]
            if description and description not in (row.details or ""):
                row.details = f"{row.details or ''} {description}".strip()
            if summer_text(description) and row.season != "verano":
                row.season = "verano"
            if out_of_season(row, today):
                db.commit()
                continue  # la descripción dice manga corta, lino…: fuera hasta mayo
            photos = _save_photos(connector, detail.photo_urls)
        except Exception as exc:
            if not isinstance(exc, ShopError):
                log.exception("Compras: error inesperado con %s", row.product_ref)
            row.last_checked_at = None  # un fallo de red no dice nada del producto: se podrá reintentar
            db.commit()
            if isinstance(exc, (BlockedError, BrowserUnavailable)):
                stopped.add(row.store)
                failed(shops.CONNECTORS[row.store].name, exc)
            else:
                failed(row.name, exc)
            continue
        row.status, row.batch, row.photos = NEW, today, photos
        _detail_color(row, detail)
        if not row.color and detail.color_hex:  # el listado no lo decía; la ficha trae el tono
            row.color = estimate_color(row.store_color, detail.color_hex)
        _price_from(row, detail)
        row.store_color_hex, row.sizes, row.in_stock = detail.color_hex, detail.sizes, True
        row.first_seen_at = now_utc()
        _apply_detail(row, detail)
        row.score, row.reasons = context.score(row)  # con la descripción ya leída
        db.commit()
        promoted[row.product_ref] = row.score
        shown.add(row.product_ref)
        family |= siblings
        if row.maker_code:
            taken[row.maker_code] = row
    return list(promoted.values())


# Lo que cuenta como «esa zapatilla ya está» al elegir propuestas: enseñándose, apartada como otro color, en
# Me gustan, comprada o descartada (descartarla en una tienda es descartarla en todas).
_CODE_TAKEN = (NEW, VARIANT, LIKED, BOUGHT, DISCARDED)


_codes_filled = False


def backfill_codes(db: Session) -> int:
    """Una vez por arranque: el código de fabricante de lo guardado antes de que se apuntara (Courir y
    Nike ya lo traían en `store_data`). Devuelve cuántos se han puesto."""
    global _codes_filled
    if _codes_filled:
        return 0
    stores = [key for key, connector in shops.CONNECTORS.items() if hasattr(connector, "maker_code")]
    filled = 0
    for row in db.scalars(select(ShopItem).where(ShopItem.maker_code.is_(None), ShopItem.store.in_(stores))):
        code = shops.maker_code(row.store, row.store_data or {})
        if code:
            row.maker_code = code
            filled += 1
    db.commit()
    _codes_filled = True
    return filled


def _taken_codes(db: Session) -> dict[str, ShopItem]:
    rows = db.scalars(select(ShopItem).where(ShopItem.maker_code.is_not(None), ShopItem.status.in_(_CODE_TAKEN)))
    return {row.maker_code: row for row in rows if row.maker_code}


SAME_SCORE = 1.0  # dos notas a menos de esto son «la misma» al elegir entre copias: manda el precio


def _better(value: float, price: int, other_value: float, other_price: int) -> bool:
    """¿Sale mejor (value, price) que la otra copia? Más nota; a igualdad (casi), más barata."""
    if abs(value - other_value) >= SAME_SCORE:
        return value > other_value
    return price < other_price


def _beats(value: float, row: ShopItem, rival: ShopItem) -> bool:
    """¿Desbanca esta candidata a la misma zapatilla de otra tienda? Solo si la otra está pendiente de ver
    (no se ha dicho nada de ella) y esta sale mejor."""
    return rival.status == NEW and rival.store != row.store and _better(
        value, row.price_cents, rival.score or 0.0, rival.price_cents)


def _best_by_code(ranked: list[tuple]) -> dict[str, str]:
    """De las candidatas con código de fabricante, la mejor de cada código (ver `_better`)."""
    best: dict[str, tuple[float, int, str]] = {}
    for value, _reasons, row in ranked:
        code = row.maker_code
        if code and (code not in best or _better(value, row.price_cents, best[code][0], best[code][1])):
            best[code] = (value, row.price_cents, row.product_ref)
    return {code: ref for code, (_value, _price, ref) in best.items()}


def _swap_out(row: ShopItem) -> None:
    """Una propuesta pendiente de ver deja su sitio a la misma zapatilla de otra tienda, que sale mejor:
    vuelve a ser candidata (sin fotos) y esta semana no se vuelve a intentar."""
    _drop_photos(row)
    row.status = CANDIDATE
    row.last_checked_at = now_utc()


ALSO_IN_STATUSES = (CANDIDATE, NEW, VARIANT, LIKED, SEARCHED)


def also_in(item: ShopItem) -> list[dict]:
    """«También en»: la misma zapatilla (mismo código de fabricante) en otras tiendas, la más barata de
    cada una: [{"store", "store_name", "price_cents", "url"}], de la más barata a la más cara. Solo lo que
    sigue en su catálogo; vacío si no se sabe el código."""
    db = object_session(item)
    if db is None or not item.maker_code:
        return []
    rows = db.scalars(select(ShopItem).where(
        ShopItem.maker_code == item.maker_code, ShopItem.store != item.store, ShopItem.status.in_(ALSO_IN_STATUSES),
    ))
    cheapest: dict[str, ShopItem] = {}
    for row in rows:
        if row.store in shops.CONNECTORS and row.price_cents and (
                row.store not in cheapest or row.price_cents < cheapest[row.store].price_cents):
            cheapest[row.store] = row
    return [
        {"store": row.store, "store_name": shops.CONNECTORS[row.store].name, "price_cents": row.price_cents,
         "url": row.url}
        for row in sorted(cheapest.values(), key=lambda r: (r.price_cents, r.store))
    ]


def _shown_this_round(db: Session) -> tuple[set[str], set[str]]:
    """Lo que se está enseñando en esta tanda (pendiente, apartado como otro color, o decidido y aún
    deshacible) y sus colores hermanos: (sus referencias, las de sus hermanos)."""
    rows = db.scalars(
        select(ShopItem).where(or_(ShopItem.status.in_((NEW, VARIANT)), ShopItem.can_undo.is_(True)))
    )
    shown: set[str] = set()
    family: set[str] = set()
    for row in rows:
        shown.add(row.product_ref)
        family.update(s["product_ref"] for s in family_of(row))
    return shown, family - shown


def _failure_log(result: dict):
    """Devuelve la función que apunta un fallo en `result` («Camisas: HTTP 403»)."""

    def failed(what: str, exc: Exception) -> None:
        message = str(exc) if isinstance(exc, ShopError) else "error inesperado en el conector"
        result["failed"] += 1
        result["errors"].append(f"{what}: {message}")

    return failed


def _resumable(cycle, today: date) -> bool:
    """¿Se puede retomar el recorrido que quedó a medias? Sí si empezó hace menos de una semana."""
    if not isinstance(cycle, dict) or not isinstance(cycle.get("done"), list):
        return False
    start = _parse_day(cycle.get("start"))
    return start is not None and 0 <= (today - start).days < 7


def _start_cycle(db: Session, store: str, today: date) -> int:
    """Lo que se hace una vez por recorrido, en cuanto la tienda responde: las propuestas de tandas
    anteriores que no se llegaron a valorar se retiran (las de la reserva que nunca se enseñaron vuelven
    a ser candidatos), los colores apartados también, y se cierra la posibilidad de deshacer.
    Devuelve cuántas caducaron."""
    expired = 0
    stale = select(ShopItem).where(
        ShopItem.store == store, ShopItem.status.in_((NEW, VARIANT)), ShopItem.batch < today
    )
    for item in db.scalars(stale):
        was_new = item.status == NEW
        _retire_unseen(item)
        if item.status == CANDIDATE:
            item.last_checked_at = None  # se puede volver a proponer
        elif was_new:
            expired += 1
    _set(db, K_MORE, None)
    db.commit()
    _close_undo(db, store)
    return expired


def _stale(row: ShopItem, cycle_at: datetime) -> bool:
    """¿No ha salido en el listado desde que empezó el recorrido?"""
    listed = _aware(row.listed_at)
    return listed is None or listed < cycle_at


def refresh_store(db: Session, store: str, today: date | None = None, limit: int | None = None,
                  run: "shops.crawl.Crawl | None" = None) -> dict:
    """Consulta UNA tienda: recorre su catálogo ENTERO (todas las páginas de cada sección activa, solo
    datos, sin fotos) y lo guarda como candidatos; puntúa todos los candidatos con lo aprendido y solo
    de los mejores baja ficha y fotos (su parte de la tanda); y revisa sus «me gusta».

    `run` es el recorrido (pausas, topes, avance, cancelación; ver shops/crawl.py). Sin él, sin pausas.

    Si se corta a medias (una sección que falla, un bloqueo, la cancelación), lo leído se guarda y la
    próxima vez se retoma por la sección donde iba (`cycle` en el estado de la tienda), más despacio si
    fue un bloqueo. Solo cuando todas las secciones se han leído enteras cuenta como consulta hecha
    (`ok_day`) y se retiran los candidatos que la tienda ya no lista.

    Nunca lanza por culpa de la tienda: lo que falla se apunta, se guarda en el estado de la tienda
    (`store_status`) y se sigue con lo demás.
    """
    now = now_utc()
    started_clock = time.monotonic()
    today = today or outfits.local_today()
    # El cupo de la tanda se reparte entre las tiendas activadas.
    limit = math.ceil((config.SHOP_BATCH_SIZE if limit is None else limit) / max(1, len(enabled_stores(db))))
    connector = shops.CONNECTORS[store]
    previous = store_status(db, store) or {}
    result = {
        "at": now.isoformat(), "day": today.isoformat(), "ok": False, "ok_day": previous.get("ok_day"),
        "found": 0, "added": 0, "expired": 0, "failed": 0, "error": None, "errors": [],
        "complete": False, "cancelled": False, "sections": 0, "sections_total": 0, "pages": 0, "seconds": 0,
    }
    errors: list[str] = result["errors"]
    failed = _failure_log(result)

    # Se apunta ya el intento: si el proceso muere a medias, hoy no se vuelve a insistir.
    _save_status(db, store, {**previous, "day": today.isoformat()})
    db.commit()

    # Sin navegador en este equipo, o si la tienda ha bloqueado hoy, ni se intenta.
    why = shops.unavailable(store) or blocked_today(db, store, today)
    if why:
        message = f"{connector.name}: {why}"
        result.update(error=message, errors=[message], failed=1, cycle=previous.get("cycle"))
        if previous.get("blocked_day") == today.isoformat() or shops.browser.blocked(store):
            result["blocked_day"] = today.isoformat()
        _save_status(db, store, result)
        db.commit()
        log.info("Compras: %s no se consulta: %s", store, why)
        return result

    run = run or shops.crawl.Crawl(store)
    progress = run.progress
    active = active_categories(db, store)
    cycle = previous.get("cycle") if _resumable(previous.get("cycle"), today) else None
    resumed = cycle is not None
    if cycle is None:
        cycle = {"start": today.isoformat(), "at": now.isoformat(), "done": [], "slow": False}
    elif cycle.get("slow"):
        # La última vez la tienda bloqueó a mitad: al retomar se va más despacio.
        run.pause = tuple(value * config.SHOP_SLOW_FACTOR for value in run.pause)
    cycle_at = _aware(_parse_moment(cycle.get("at"))) or now
    covered = getattr(connector, "covered_by", None) or {}
    # Las secciones contenidas en otras (marcas, novedades), al final: si las que las contienen se leen
    # enteras, ya no hace falta recorrerlas.
    todo = sorted((s for s in active if s not in cycle["done"]), key=lambda s: s in covered)
    progress.update(store=store, name=connector.name, phase="catalogo", section=None, section_label=None,
                    resumed=resumed)
    run.start_sections(len(active), len(active) - len(todo))
    result["sections_total"] = len(active)

    started = resumed  # caducar lo de la tanda anterior ya se hizo al empezar este recorrido
    shown: set[str] | None = None
    old: dict[str, ShopItem] = {}
    fresh: set[str] = set()
    listed_shown: dict[str, object] = {}  # lo ya enseñado que sigue en el listado: ref -> producto
    stop_store = cancelled = False
    section_pages: dict[str, int] = dict(previous.get("section_pages") or {})

    def load_rows() -> None:
        nonlocal shown, old
        if shown is None:
            shown = set(db.scalars(select(ShopItem.product_ref).where(ShopItem.status != CANDIDATE)))
            old = {
                row.product_ref: row
                for row in db.scalars(select(ShopItem).where(ShopItem.store == store, ShopItem.status == CANDIDATE))
            }

    def drop_section(slug: str) -> None:
        """La sección se ha leído entera: fuera sus candidatos que no han salido en este recorrido."""
        for ref, row in list(old.items()):
            if row.section == slug and ref not in fresh and _stale(row, cycle_at):
                db.delete(row)
                del old[ref]

    def save_cycle() -> None:
        _save_status(db, store, {**(store_status(db, store) or previous), "day": today.isoformat(), "cycle": cycle,
                                     "section_pages": section_pages})
        db.commit()

    for slug in todo:
        label = connector.categories.get(slug, slug)
        container = covered.get(slug)
        if container and all(c in active and c in cycle["done"] for c in container):
            load_rows()
            drop_section(slug)
            cycle["done"].append(slug)
            run.section_end(skipped=True)
            save_cycle()
            continue
        run.section_start(slug, label)
        # Las páginas que tuvo la última vez: así la barra sabe el total desde la primera página (si
        # la tienda lo dice, como JD o Pull&Bear, manda lo que diga).
        known_pages = (previous.get("section_pages") or {}).get(slug)
        if known_pages:
            run.section_total(known_pages)
        partial = None
        try:
            products = connector.list_category(slug)
        except Partial as exc:
            products, partial = exc.products, exc.cause
        except Cancelled:
            cancelled = True
            break
        except (BlockedError, BrowserUnavailable) as exc:
            failed(connector.name, exc)
            if isinstance(exc, BlockedError):
                result["blocked_day"] = today.isoformat()
                cycle["slow"] = True
            stop_store = True
            break
        except Exception as exc:  # ni la tienda ni un conector roto pueden tumbar la tanda
            if not isinstance(exc, ShopError):
                log.exception("Compras: error inesperado en %s/%s", store, slug)
            failed(label, exc)
            run.section_end(skipped=True)
            continue
        result["ok"] = True
        if not started:
            result["expired"] += _start_cycle(db, store, today)
            started = True
        load_rows()
        result["found"] += len(products)
        for product in products:
            ref = product.product_ref
            if ref in shown:
                listed_shown.setdefault(ref, product)
            elif ref not in fresh:  # la misma prenda puede salir en dos categorías
                fresh.add(ref)
                old[ref] = _store_candidate(db, old.get(ref), product, today)
        if partial is None:
            # Una tienda que a propósito no lee la sección entera (Uniqlo por API.SH: para de pasar páginas en
            # cuanto todo está ya visto, para no gastar créditos) la da por leída, pero sin retirar nada.
            listed_all = getattr(connector, "listed_all", None)
            if listed_all is None or listed_all(slug):
                drop_section(slug)
            cycle["done"].append(slug)
            section_pages[slug] = int(progress.get("section_pages") or 0)
            run.section_end()
        elif isinstance(partial, Cancelled):
            cancelled = True
        elif isinstance(partial, (BlockedError, BrowserUnavailable)):
            failed(connector.name, partial)
            if isinstance(partial, BlockedError):
                result["blocked_day"] = today.isoformat()
                cycle["slow"] = True
            stop_store = True
        else:
            failed(label, partial)
            run.section_end()
        save_cycle()
        if cancelled or stop_store:
            break

    complete = not cancelled and all(s in cycle["done"] for s in active)
    result["sections"] = sum(1 for s in active if s in cycle["done"])
    if complete:
        # Secciones que ya no interesan: fuera sus candidatos.
        load_rows()
        for ref, row in list(old.items()):
            if row.section not in active and ref not in fresh:
                db.delete(row)
        db.commit()
        result["ok"] = result["complete"] = True
    result["cancelled"] = cancelled

    # El detalle y las fotos, solo de los mejores de TODO el catálogo guardado (también lo leído otros
    # días si se ha retomado). Lo que ya está pendiente de este recorrido cuenta para su cupo.
    blocked_now = bool(result.get("blocked_day") or shops.browser.blocked(store))
    if result["ok"] and not cancelled and not blocked_now:
        run.phase("eligiendo")
        if _lock.acquire(timeout=600):
            try:
                pending = list(db.scalars(select(ShopItem).where(ShopItem.store == store, ShopItem.status == NEW)))
                in_cycle = sum(1 for item in pending if item.batch and item.batch >= _parse_day(cycle["start"]))
                want = max(0, limit - in_cycle)
                if want:
                    context = Context.load(db)
                    rows = candidates_left(db, today, store=store)
                    ranked = _ranked(context, rows, want * 2, pending)
                    run.phase("propuestas", want)
                    result["added"] = len(_promote(db, context, ranked, want, today, failed,
                                                   stop=run.cancel.is_set, on_step=run.step))
            finally:
                _lock.release()

    # Los «me gusta» de esta tienda: ¿siguen ahí y queda alguna talla? Si han salido en el listado, con lo
    # que dice el listado; si no, se pide su ficha.
    stopped = stop_store or cancelled or blocked_now
    liked = [] if stopped else list(db.scalars(select(ShopItem).where(ShopItem.store == store, ShopItem.status == LIKED)))
    for item in liked:
        listed = listed_shown.get(item.product_ref)
        try:
            detail = None
            if listed is not None:
                item.store_data = {**(item.store_data or {}), **(listed.store_data or {})}
                _price_from(item, listed)  # el precio de esta semana, y si está rebajado, según el listado
                detail = shops.cached_detail(store, item.store_data)
            if detail is None:
                detail = connector.detail(item.store_data)
            if detail is not None and detail.in_stock and detail.photo_urls and not _has_photos(item):
                item.photos = _save_photos(connector, detail.photo_urls)  # buscado sin foto: ya la tiene
        except (BlockedError, BrowserUnavailable) as exc:
            failed(connector.name, exc)
            if isinstance(exc, BlockedError):
                result["blocked_day"] = today.isoformat()
            break
        except Exception as exc:
            if not isinstance(exc, ShopError):
                log.exception("Compras: error inesperado al comprobar %s", item.product_ref)
            failed(item.name, exc)
            continue
        item.last_checked_at = now_utc()
        if detail is None or not detail.in_stock:
            _retire(item, EXPIRED)
            item.in_stock = False
            result["expired"] += 1
        else:
            item.sizes, item.in_stock = detail.sizes, True
            _price_from(item, detail)
            _apply_detail(item, detail)  # de paso, los colores: los guardados antes de apuntarlos se ponen al día
            _detail_color(item, detail)  # y lo que la ficha sepa para volver a pedirla (Pull&Bear, Bershka)
        db.commit()

    if complete:
        result["ok_day"] = today.isoformat()
        result["cycle"] = None
    else:
        result["cycle"] = cycle
    if shops.browser.blocked(store):
        result["blocked_day"] = today.isoformat()
    # Un bloqueo o un navegador que no arranca va primero: es lo que hay que ver en el panel.
    first = next((e for e in errors if e.startswith(f"{connector.name}: ")), None)
    if first:
        errors.remove(first)
        errors.insert(0, first)
    result["error"] = errors[0] if errors else None
    result["errors"] = errors[:20]
    result["pages"] = int(progress.get("pages", 0))
    result["section_pages"] = section_pages
    result["seconds"] = round(time.monotonic() - started_clock)
    _save_status(db, store, result)
    db.commit()
    log.info(
        "Compras: %s consultada (%s vistos, %s/%s secciones, %s páginas, %s nuevos, %s caducados, %s fallos, %s s%s)",
        store, result["found"], result["sections"], result["sections_total"], result["pages"], result["added"],
        result["expired"], result["failed"], result["seconds"], ", cancelada" if cancelled else "",
    )
    return result


def refresh(db: Session, today: date | None = None, limit: int | None = None, stores: list[str] | None = None,
            night: bool = False, cancel: threading.Event | None = None, progress: dict | None = None) -> dict:
    """Una consulta: recorre el catálogo de las tiendas indicadas (por defecto, todas las activadas),
    una detrás de otra. `night`: la automática, con las pausas largas de la noche; si no («Consultar
    ahora»), el mismo recorrido con pausas algo menores. `cancel` la corta (se guarda lo leído) y
    `progress` es el dict donde se va apuntando por dónde va (lo lee el panel)."""
    total = {"ok": False, "found": 0, "added": 0, "expired": expire_old(db), "failed": 0, "errors": [],
             "cancelled": False}
    backfill_codes(db)
    clean_lookups(db, LOOKUP_KEEP_ON_REFRESH)  # antes de mirar qué se ha enseñado ya: un «buscado» no cuenta
    pause = config.SHOP_NIGHT_PAUSE if night else config.SHOP_DAY_PAUSE
    cancel = cancel or threading.Event()
    queue = [store for store in (stores if stores is not None else enabled_stores(db)) if store in shops.CONNECTORS]
    for index, store in enumerate(queue):
        if cancel.is_set():
            total["cancelled"] = True
            break
        state = progress if progress is not None else {}
        state.clear()
        state.update(started_at=now_utc().isoformat(), night=night, pages=0, products=0, store=store,
                     store_index=index + 1, stores_total=len(queue))
        run = shops.crawl.Crawl(store, pause=pause, cancel=cancel, progress=state)
        try:
            with shops.crawl.running(run):
                result = refresh_store(db, store, today, limit, run)
        except Exception:  # un fallo nuestro con una tienda no impide consultar las demás
            log.exception("Compras: la consulta de %s falló", store)
            db.rollback()
            message = "error inesperado de la app al consultar la tienda"
            result = {
                **(store_status(db, store) or {}), "at": now_utc().isoformat(),
                "day": (today or outfits.local_today()).isoformat(), "ok": False, "found": 0, "added": 0,
                "expired": 0, "failed": 1, "error": message, "errors": [message],
            }
            _save_status(db, store, result)
            db.commit()
        total["ok"] = total["ok"] or result["ok"]
        for key in ("found", "added", "expired", "failed"):
            total[key] += result[key]
        total["errors"] += result["errors"]
        total["cancelled"] = total["cancelled"] or bool(result.get("cancelled"))
    return total


def more(db: Session, store: str | None = None, category: str | None = None, limit: int | None = None,
         today: date | None = None, only: ShopFilter | None = None) -> dict:
    """«Ver más»: la siguiente tanda sin esperar al día de consulta.

    Vuelve a puntuar los candidatos guardados con los gustos de ahora (respetando el filtro de tienda
    y de tipo de prenda), y solo de los mejores baja ficha y fotos. No pide el catálogo otra vez.

    Devuelve, y deja guardado para la interfaz (`last_more`):
    {"at", "added": propuestas nuevas, "mean": su nota media, "low": si encajan ya menos (LOW_FIT),
     "failed", "error": el primer fallo en claro, "errors"}
    """
    today = today or outfits.local_today()
    limit = config.SHOP_MORE_SIZE if limit is None else limit
    result = {"at": now_utc().isoformat(), "added": 0, "mean": None, "low": False, "failed": 0, "error": None,
              "errors": []}
    context = Context.load(db)
    rows = [row for row in candidates_left(db, today, store, category, only) if row.store not in _crawling_stores()]
    ranked = _ranked(context, rows, limit * 2, _pending(db))
    scores = _promote(db, context, ranked, limit, today, _failure_log(result))
    _note_blocks(db, today)
    if scores:
        result["added"] = len(scores)
        result["mean"] = round(sum(scores) / len(scores), 1)
        result["low"] = result["mean"] < LOW_FIT
    result["error"] = result["errors"][0] if result["errors"] else None
    result["errors"] = result["errors"][:20]
    _set(db, K_MORE, result)
    db.commit()
    log.info("Compras: ver más (%s nuevas, nota media %s, %s peticiones fallidas)",
             result["added"], result["mean"], result["failed"])
    return result


def last_more(db: Session) -> dict | None:
    """Cómo fue el último «Ver más» desde la última consulta semanal, o None si no ha habido."""
    return _get(db, K_MORE)


def _note_blocks(db: Session, today: date) -> None:
    """Si una tienda ha bloqueado fuera de la consulta («Ver más», la reserva): que el panel lo diga y
    que hoy no se insista."""
    for key, connector in shops.CONNECTORS.items():
        why = shops.browser.blocked(key)
        status = store_status(db, key) or {}
        if why and status.get("blocked_day") != today.isoformat():
            message = f"{connector.name}: {why}"
            _save_status(db, key, {**status, "blocked_day": today.isoformat(), "error": message,
                                   "errors": [message, *(status.get("errors") or [])][:20]})
    db.commit()


def _pending(db: Session) -> list[ShopItem]:
    """Las propuestas que quedan por ver, de las tiendas activadas."""
    return list(db.scalars(
        select(ShopItem).where(ShopItem.status == NEW, ShopItem.store.in_(enabled_stores(db)))
    ))


# ---------- La reserva: fotos por adelantado


def prepare_colors(db: Session, items: list[ShopItem] | None = None, limit: int | None = None) -> int:
    """Deja preparados (ficha y fotos) otros colores de las propuestas pendientes en las tiendas que no
    pueden traer un color al momento (`prepared_colors`: JD Sports, que se lee con navegador). Solo los
    que han salido en el listado (de hombre y con talla): se sacan de lo que guardó el listado y las
    fotos de su CDN, sin navegador. Quedan como «variante» (no se proponen aparte ni cuentan) y, si
    nunca se llegan a ver, vuelven a ser candidatos con la siguiente consulta. Hasta `SHOP_COLOR_PREP`
    colores por propuesta, contando el que se ve. Devuelve cuántos se han preparado."""
    limit = config.SHOP_COLOR_PREP if limit is None else limit
    stores = [key for key, c in shops.CONNECTORS.items() if getattr(c, "prepared_colors", False)]
    if items is None:
        items = list(db.scalars(select(ShopItem).where(ShopItem.status == NEW, ShopItem.store.in_(stores))))
    prepared = 0
    for item in items:
        if item.store not in stores or not item.siblings or blocked_today(db, item.store):
            continue
        others = [s["product_ref"] for s in family_of(item) if s["product_ref"] != item.product_ref]
        if not others:
            continue
        rows = {row.product_ref: row for row in db.scalars(select(ShopItem).where(ShopItem.product_ref.in_(others)))}
        ready = sum(1 for ref in others if ref in rows and _color_ready(db, rows[ref]))
        connector = shops.CONNECTORS[item.store]
        for ref in others:
            if ready >= limit - 1:
                break
            row = rows.get(ref)
            if row is None or row.status != CANDIDATE:
                continue
            detail = shops.cached_detail(row.store, row.store_data or {})
            if detail is None or not detail.photo_urls or not detail.in_stock:
                continue
            try:
                photos = _save_photos(connector, detail.photo_urls)
            except ShopError as exc:
                log.info("Compras: no se pudo preparar el color %s: %s", ref, exc)
                continue
            row.status, row.prev_status, row.batch, row.photos = VARIANT, CANDIDATE, item.batch, photos
            row.sizes, row.in_stock, row.can_undo = detail.sizes, True, False
            row.first_seen_at = now_utc()
            _apply_detail(row, detail)
            db.commit()
            ready += 1
            prepared += 1
    return prepared


def _color_ready(db: Session, row: ShopItem) -> bool:
    """¿Se puede enseñar ese color al momento (sin ir a la tienda)?"""
    return bool(already(db, row)) or (row.status in (NEW, SEARCHED, VARIANT) and _has_photos(row))


def _fill_photos(db: Session) -> int:
    """Lo que el buscador encontró en lo guardado sin poder bajar sus fotos (un producto de una tienda
    de navegador sin datos del listado) y se guardó o se dejó buscado: si ya se puede sin navegador (con lo
    que guardó el listado), sus fotos. Lo que necesita el navegador lo baja `fetch_missing_photos`."""
    filled = 0
    waiting = db.scalars(select(ShopItem).where(ShopItem.status.in_((SEARCHED, LIKED))))
    for item in waiting:
        if _has_photos(item) or not reachable(db, item.store):
            continue
        try:
            detail = _detail_for(item, offline=True)
            if detail is None or not detail.photo_urls:
                continue
            item.photos = _save_photos(shops.CONNECTORS[item.store], detail.photo_urls)
        except Exception as exc:
            if not isinstance(exc, ShopError):
                log.exception("Compras: error inesperado al bajar las fotos de %s", item.product_ref)
            continue
        if not item.sizes:
            item.sizes = detail.sizes
        _price_from(item, detail)
        _apply_detail(item, detail)
        db.commit()
        filled += 1
    return filled


# ---------- Las fotos que faltan en lo guardado (tiendas de navegador)
#
# Lo que se guarda desde el buscador (o se busca y se queda sin foto) puede ser de una tienda que solo se lee
# con navegador y cuyo listado no dejó lo necesario (un producto de una consulta antigua): entonces no tiene
# foto. Un trabajo corto en segundo plano (`photos_soon`) abre el navegador SOLO para esas fichas, una cada
# vez y con las pausas del propio navegador, y baja sus fotos, tallas y colores. Nunca dentro de una petición
# HTTP ni con una consulta del catálogo en marcha. Si falla, se reintenta desde el bucle automático, cada vez
# más espaciado; si la tienda bloquea, se respeta como en el resto (hasta mañana, y el panel lo dice).

PHOTO_JOB_MAX = 8  # fichas por vuelta, como mucho: lo que quede, en la siguiente
PHOTO_RETRY = timedelta(hours=3)  # tras un intento fallido, lo que se espera (se dobla con cada fallo)…
PHOTO_RETRY_MAX = timedelta(days=2)  # …hasta este tope
# item -> (intentos fallidos, último intento). En memoria: al reiniciar la app se prueba otra vez.
_photo_tries: dict[int, tuple[int, datetime]] = {}


def _photo_wait(item_id: int, now: datetime) -> bool:
    """¿Falló hace poco y aún no toca reintentar?"""
    tries, last = _photo_tries.get(item_id, (0, None))
    if not tries or last is None:
        return False
    return now - last < min(PHOTO_RETRY * 2 ** (tries - 1), PHOTO_RETRY_MAX)


def _photo_failed(item_id: int, now: datetime) -> None:
    tries, _last = _photo_tries.get(item_id, (0, None))
    _photo_tries[item_id] = (tries + 1, now)


def missing_photos(db: Session, now: datetime | None = None) -> list[ShopItem]:
    """Lo guardado (buscado o en Me gustan) que sigue sin foto y se puede intentar ya: de una tienda que hoy
    responde (con navegador en este equipo y sin bloqueo), que no se esté consultando ahora y que no haya
    fallado hace poco."""
    now = now or now_utc()
    crawling = _crawling_stores()
    found = []
    for item in db.scalars(select(ShopItem).where(ShopItem.status.in_((SEARCHED, LIKED))).order_by(ShopItem.id)):
        if _has_photos(item) or item.store not in shops.CONNECTORS or item.store in crawling:
            continue
        if _photo_wait(item.id, now) or not reachable(db, item.store):
            continue
        found.append(item)
    return found


def fetch_missing_photos(db: Session, limit: int = PHOTO_JOB_MAX, stop=None, today: date | None = None) -> dict:
    """Baja las fotos (y de paso tallas, colores y precio) de lo guardado que se quedó sin ellas, pidiendo
    su ficha a la tienda: la que guardó el listado si la hay y, si no, la de verdad, con el navegador en las
    tiendas que lo necesitan. Una ficha cada vez, como mucho `limit`. Abre su propia sesión de navegador
    (solo se arranca si alguna ficha lo pide), así que SOLO se llama desde un trabajo en segundo plano
    (`photos_soon`) o desde los tests. `stop()` corta entre ficha y ficha (ha empezado una consulta).

    Si la tienda bloquea, no se le pide nada más y queda apuntado para el panel (`_note_blocks`). Si la ficha
    dice que ya no existe, no se toca: la revisión semanal de los «me gusta» lo retira como siempre.
    Devuelve {"photos": cuántos ya tienen foto, "failed", "errors"}."""
    today = today or outfits.local_today()
    result = {"photos": 0, "failed": 0, "errors": []}
    failed = _failure_log(result)
    stopped: set[str] = set()
    with shops.browser.session():
        for item in missing_photos(db)[:limit]:
            if stop is not None and stop():
                break
            if item.store in stopped or not reachable(db, item.store, today):
                continue
            connector = shops.CONNECTORS[item.store]
            now = now_utc()
            photos: list[str] = []
            try:
                detail = _detail_for(item)
                if detail is not None and detail.photo_urls:
                    photos = _save_photos(connector, detail.photo_urls)
            except (BlockedError, BrowserUnavailable) as exc:
                stopped.add(item.store)
                _photo_failed(item.id, now)
                failed(connector.name, exc)
                log.info("Compras: sin fotos de %s por ahora: %s", item.product_ref, exc)
                continue
            except Exception as exc:
                if not isinstance(exc, ShopError):
                    log.exception("Compras: error inesperado al traer las fotos de %s", item.product_ref)
                _photo_failed(item.id, now)
                failed(item.name, exc)
                continue
            db.refresh(item)  # mientras se hablaba con la tienda ha podido cambiar (quitado, comprado…)
            if item.status not in (SEARCHED, LIKED) or _has_photos(item) or not photos:
                for photo_id in photos:
                    storage.delete(photo_id)
                if not photos and item.status in (SEARCHED, LIKED) and not _has_photos(item):
                    _photo_failed(item.id, now)  # ya no existe o no tiene foto de producto: más tarde
                continue
            item.photos = photos
            if detail.sizes or not item.sizes:
                item.sizes = detail.sizes
            _price_from(item, detail)
            _detail_color(item, detail)
            if item.color in ("", "multicolor") and detail.color_hex:
                item.color = estimate_color(item.store_color, detail.color_hex)
            if detail.color_hex:
                item.store_color_hex = detail.color_hex
            description = " ".join((detail.description or "").split())[:DESCRIPTION_MAX]
            if description and description not in (item.details or ""):
                item.details = f"{item.details or ''} {description}".strip()
            _apply_detail(item, detail)
            _photo_tries.pop(item.id, None)
            db.commit()
            result["photos"] += 1
    _note_blocks(db, today)
    if result["photos"] or result["failed"]:
        log.info("Compras: fotos que faltaban (%s bajadas, %s fallos)", result["photos"], result["failed"])
    return result


def needs_top_up(db: Session) -> bool:
    """¿Quedan menos propuestas por ver de las que debe haber en la reserva, y algo con lo que reponer?"""
    stores = enabled_stores(db)
    if not stores:
        return False
    pending = db.scalar(select(func.count()).select_from(ShopItem).where(
        ShopItem.status == NEW, ShopItem.store.in_(stores))) or 0
    if pending >= config.SHOP_RESERVE_LOW:
        return False
    return (db.scalar(select(func.count()).select_from(ShopItem).where(
        ShopItem.status == CANDIDATE, ShopItem.store.in_(stores), ShopItem.last_checked_at.is_(None))) or 0) > 0


FILTER_RESERVE = 10  # propuestas que se reponen de un tipo cuando se agota con el filtro puesto


def top_up(db: Session, today: date | None = None, target: int | None = None, store: str | None = None,
           category: str | None = None, only: ShopFilter | None = None) -> dict:
    """Repone la reserva: baja ficha y fotos de los mejores candidatos (puntuados con lo de ahora y sin
    repetir lo que ya está en la cola) hasta tener `target` propuestas por ver; prepara los colores de
    las tiendas que lo necesitan y baja las fotos que esperaban. Las tiendas de navegador solo con lo
    que guardó el listado: de día no se abre el navegador. No apunta nada en el panel salvo un bloqueo.

    Con `store` o `category` (el filtro de Descubrir se ha quedado sin propuestas), repone solo de eso,
    hasta FILTER_RESERVE.
    """
    today = today or outfits.local_today()
    only = only or ShopFilter.of(store, category)
    filtered = not only.empty
    target = (FILTER_RESERVE if filtered else config.SHOP_RESERVE) if target is None else target
    result = {"added": 0, "colors": 0, "photos": 0, "failed": 0, "errors": []}
    pending = _pending(db)
    mine = [p for p in pending if only.matches(p)]
    want = target - len(mine)
    if want > 0:
        context = Context.load(db)
        rows = [row for row in candidates_left(db, today, only=only) if row.store not in _crawling_stores()]
        if rows:
            ranked = _ranked(context, rows, want * 2, pending)
            result["added"] = len(_promote(db, context, ranked, want, today, _failure_log(result), offline=True))
    result["colors"] = prepare_colors(db)
    result["photos"] = _fill_photos(db)
    _note_blocks(db, today)
    if result["added"] or result["colors"] or result["photos"]:
        log.info("Compras: reserva repuesta (%s propuestas, %s colores, %s fotos)",
                 result["added"], result["colors"], result["photos"])
    return result


# ---------- El buscador por referencia


class LookupFailed(Exception):
    """El buscador no tiene nada que enseñar. El mensaje va tal cual a la pantalla.

    `reason`: «nada» (no existe o no se entiende lo que se busca), «tienda» (la tienda no responde)
    u «ocupado» (hay una consulta del catálogo en marcha).
    """

    def __init__(self, message: str, reason: str = "nada"):
        super().__init__(message)
        self.reason = reason


def clean_lookups(db: Session, keep: timedelta = LOOKUP_KEEP, now: datetime | None = None) -> int:
    """Quita los «buscados» con los que no se ha hecho nada en `keep`, con sus fotos. El que ya
    existía antes de buscarlo (descartado, caducado…) vuelve a lo que era; el resto se borra, como
    si no se hubiera buscado nunca."""
    now = now or now_utc()
    cleaned = 0
    for item in db.scalars(select(ShopItem).where(ShopItem.status == SEARCHED)):
        seen = _aware(item.first_seen_at)
        if seen and now - seen < keep:
            continue
        _drop_photos(item)
        if item.prev_status:
            if item.prev_status == CANDIDATE:
                item.last_checked_at = None  # vuelve al catálogo guardado: se puede proponer
            item.status, item.prev_status, item.can_undo = item.prev_status, None, False
        else:
            db.delete(item)
        cleaned += 1
    if cleaned:
        db.commit()
    return cleaned


def already(db: Session, item: ShopItem) -> str | None:
    """Si un resultado del buscador ya estaba guardado: «gustado», «comprado» (y la prenda sigue en
    el armario) o None."""
    if item.status == LIKED:
        return LIKED
    if item.status == BOUGHT and item.garment_id and db.get(Garment, item.garment_id) is not None:
        return BOUGHT
    return None


def _search_stores(query: str) -> list[tuple[object, object]]:
    """Pregunta a cada tienda que sepa buscar. Devuelve (conector, producto) o lanza LookupFailed.

    Se busca en todas, estén activadas o no: activar una tienda es pedirle novedades cada semana, y
    quien escribe una referencia ya sabe lo que quiere.
    """
    found: list[tuple[object, object]] = []
    nothing: list[str] = []
    down: list[str] = []
    for connector in shops.CONNECTORS.values():
        search = getattr(connector, "search", None)
        if search is None:
            continue
        try:
            found += [(connector, product) for product in search(query, LOOKUP_MAX)]
        except NotThisStore:
            continue
        except SearchError as exc:
            nothing.append(str(exc))
        except ShopError as exc:
            down.append(f"{connector.name} no responde ahora ({exc})")
        except Exception:
            log.exception("Compras: error inesperado al buscar en %s", connector.key)
            down.append(f"No se pudo buscar en {connector.name}: error inesperado")
    if found:
        return found[:LOOKUP_MAX]
    if down:
        raise LookupFailed(down[0], "tienda")
    raise LookupFailed(nothing[0] if nothing else "Todavía no sé buscar en esa tienda")


def lookup(db: Session, query: str, today: date | None = None) -> list[ShopItem]:
    """El buscador: de una referencia, un enlace o un texto a productos guardados con sus fotos.

    Es síncrono (unos segundos). Lo nuevo se guarda como «buscado». Lo que ya existía se reutiliza
    en vez de duplicarse: lo que está en Descubrir, en Me gustan o comprado se devuelve tal cual
    (ver `already`), y lo descartado o caducado se vuelve a traer para poder guardarlo otra vez.
    Lanza LookupFailed, con el mensaje ya escrito, si no hay nada que enseñar.
    """
    query = " ".join((query or "").split())
    if not query:
        raise LookupFailed("Escribe una referencia, un enlace o qué prenda buscas")
    # Una búsqueda cada vez. La consulta del catálogo (que de noche dura un buen rato) no la frena: cada
    # conector ya pide sus páginas de una en una.
    if not _lookup_lock.acquire(blocking=False):
        raise LookupFailed("Ya estoy buscando otra cosa. Prueba dentro de un momento.", "ocupado")
    try:
        today = today or outfits.local_today()
        items = _lookup_saved(db, query, today) or _lookup(db, query, today)
    finally:
        _lookup_lock.release()
    if any(not _has_photos(item) for item in items):
        photos_soon()  # lo que se ha quedado sin foto, en segundo plano en cuanto se pueda
    pending = [item.id for item in items if _foreign(item.store, item.url) and not item.translated]
    worker = translate_soon(pending) if pending else None
    if worker is not None:
        worker.join(LOOKUP_TRANSLATE_SECONDS)  # si no llega, se responde en el original y se traduce después
        for item in items:
            db.refresh(item)
    return items


def _has_photos(item: ShopItem) -> bool:
    return bool(item.photos) and storage.exists(item.photos[0])


def _store_fetched(db: Session, row: ShopItem | None, product, detail, photos: list[str], today: date,
                   context: "Context") -> ShopItem:
    """Guarda como «buscado» un producto del que se acaban de bajar la ficha y las fotos (lo trae el
    buscador, o se ha elegido ese color desde otro). `row` es su fila, si ya existía."""
    before = row.status if row is not None else None
    row = _store_candidate(db, row, product, today)
    return _mark_searched(db, row, before, detail, photos, context, today)


def _mark_searched(db: Session, row: ShopItem, before: str | None, detail, photos: list[str],
                   context: "Context", today: date) -> ShopItem:
    """Deja una fila como «buscado» con su ficha y sus fotos (que pueden faltar: ver `_lookup_saved`)."""
    _drop_photos(row)  # las que pudiera tener de antes
    row.status, row.batch, row.photos = SEARCHED, today, photos
    # Lo que ya se había valorado vuelve a su estado si no se hace nada con ello.
    if before in (DISCARDED, EXPIRED, BOUGHT, CANDIDATE):
        # Un candidato del catálogo guardado vuelve a serlo (sin fotos) si no se hace nada con él.
        row.prev_status = before
    row.can_undo = False
    _price_from(row, detail)
    row.store_color_hex, row.sizes, row.in_stock = detail.color_hex, detail.sizes, detail.in_stock
    _detail_color(row, detail)
    if row.color in ("", "multicolor") and detail.color_hex:
        # El nombre del color no decía nada conocido («Bronce»): con la ficha ya se sabe el tono.
        row.color = estimate_color(row.store_color, detail.color_hex)
    row.first_seen_at = row.last_checked_at = now_utc()
    description = " ".join((detail.description or "").split())[:DESCRIPTION_MAX]
    if description and description not in (row.details or ""):
        row.details = f"{row.details or ''} {description}".strip()
    _apply_detail(row, detail)
    row.score, row.reasons = context.score(row)
    db.commit()
    return row


# ---------- Los colores de un producto


class ColorFailed(Exception):
    """No se puede enseñar ese color. El mensaje va tal cual a la pantalla. `reason`: «nada» (ese
    color ya no existe) o «tienda» (la tienda no responde)."""

    def __init__(self, message: str, reason: str = "nada"):
        super().__init__(message)
        self.reason = reason


def ensure_colors(db: Session, item: ShopItem) -> ShopItem:
    """Rellena los colores de un item guardado antes de que se apuntaran, pidiendo su ficha otra vez.

    Se hace una sola vez y solo cuando hace falta: la primera vez que se enseña su tarjeta o se abre
    su visor (y, para los «me gusta», en la consulta semanal, que ya pide esa ficha). Si la tienda
    falla no pasa nada: se queda sin saber y se vuelve a intentar la próxima vez.
    """
    connector = shops.CONNECTORS.get(item.store)
    if item.siblings is not None or connector is None or item.status == CANDIDATE:
        return item
    try:
        detail = connector.detail(item.store_data)
    except Exception as exc:
        if not isinstance(exc, ShopError):
            log.exception("Compras: error inesperado al pedir los colores de %s", item.product_ref)
        return item
    if detail is None:
        item.siblings = []  # ya no está en la tienda: no hay nada entre lo que elegir
    else:
        _apply_detail(item, detail)
        if detail.sizes:
            item.sizes = detail.sizes
        _price_from(item, detail)
    db.commit()
    return item


def _sibling_product(item: ShopItem, sibling: dict) -> shops.ShopProduct:
    """Otro color de un producto, visto como producto: lo mismo que el que se conoce, con su color."""
    name = sibling.get("name") or ""
    return shops.ShopProduct(
        store=item.store, product_ref=sibling["product_ref"], name=item.name,
        price_cents=sibling.get("price_cents") or item.price_cents, url=sibling.get("url") or item.url,
        # La rebaja de ese color, si la lista de colores la dice; si no, se sabrá con su ficha.
        old_price_cents=sibling.get("old_price_cents") if sibling.get("price_cents") else None,
        old_price_known=bool(sibling.get("price_cents")) and "old_price_cents" in sibling,
        store_color=name, section=item.section, type=item.type, category=item.category,
        color=estimate_color(name, sibling.get("hex")), pattern=item.pattern, style=item.style,
        season=item.season, details=item.details or "", store_data=dict(sibling.get("store_data") or {}),
        brand=item.brand or "",
    )


def switch_color(db: Session, item: ShopItem, product_ref: str, today: date | None = None) -> ShopItem:
    """Elegir otro color de un producto: devuelve el item de ese color, trayéndolo de la tienda (ficha
    y fotos, unos segundos) si aún no se tenía.

    El color nuevo llega como «buscado»: no es una propuesta ni enseña nada hasta que se le da «me
    gusta» o se compra, y si no se hace nada con él se limpia solo. La excepción es Descubrir: ahí el
    color elegido pasa a ser la propuesta y el que se estaba viendo se aparta («variante»), para que
    la decisión sea sobre el color que se ve y la misma prenda no salga dos veces.
    Lanza ColorFailed, con el mensaje ya escrito, si no se puede.
    """
    today = today or outfits.local_today()
    if product_ref == item.product_ref:
        return item
    sibling = next((s for s in family_of(item) if s["product_ref"] == product_ref), None)
    if sibling is None:
        raise ColorFailed("Ese color no está entre los de esta prenda")
    target = db.scalars(select(ShopItem).where(ShopItem.product_ref == product_ref)).first()
    ready = target is not None and (
        already(db, target) or (target.status in (NEW, SEARCHED, VARIANT) and _has_photos(target))
    )
    if not ready:
        connector = shops.CONNECTORS.get(item.store)
        if connector is None:
            raise ColorFailed("Esa tienda ya no está disponible", "tienda")
        try:
            # Si ese color salió en el listado, su ficha sale de ahí (sin volver a la tienda).
            detail = shops.cached_detail(item.store, target.store_data or {}) if target is not None else None
            if detail is None:
                detail = connector.detail(sibling.get("store_data") or {})
            if detail is None or not detail.photo_urls:
                # La tienda ha contestado y ese color no se puede enseñar: su circulito se quita.
                _forget_color(db, item, product_ref)
                if detail is None:
                    raise ColorFailed("Ese color ya no está en la tienda")
                raise ColorFailed("Ese color no tiene foto de producto en la tienda")
            photos = _save_photos(connector, detail.photo_urls)
        except ColorFailed:
            raise
        except NeedsBrowser as exc:  # la tienda no ha fallado: ese color solo se trae con navegador
            raise ColorFailed(str(exc), "tienda") from exc
        except Exception as exc:
            if not isinstance(exc, ShopError):
                log.exception("Compras: error inesperado al traer el color %s", product_ref)
                raise ColorFailed(f"No se pudo traer ese color de {connector.name}", "tienda") from exc
            raise ColorFailed(f"{connector.name} no responde ahora ({exc})", "tienda") from exc
        # Mientras se hablaba con la tienda ha podido cambiar algo (un «me gusta» a medio camino).
        db.refresh(item)
        target = db.scalars(select(ShopItem).where(ShopItem.product_ref == product_ref)).first()
        product = _sibling_product(item, sibling)
        if target is not None:  # lo que guardó el listado de ese color (su instantánea) no se pierde
            product.store_data = {**product.store_data, **(target.store_data or {})}
        target = _store_fetched(db, target, product, detail, photos, today, Context.load(db))
    # Es la misma familia de colores: el que se elige y el que se deja enseñan los mismos, aunque la
    # ficha de uno nombre menos que la del otro.
    _share_family(item, target)
    db.commit()
    if item.status == NEW and target.status in (NEW, SEARCHED, VARIANT):
        target.status, target.batch, target.can_undo = NEW, item.batch, False
        item.status = VARIANT
        db.commit()
    elif target.status == SEARCHED:
        target.first_seen_at = now_utc()  # se ha vuelto a mirar: el plazo de limpieza empieza otra vez
        db.commit()
    # Es la misma prenda en otro color: lo que ya estaba traducido (el nombre, la composición y el nombre
    # del color, que viene en la lista de hermanos) se hereda al momento, sin esperar a Codex. Antes el
    # título volvía al francés al cambiar de color aunque fuera el mismo.
    inherited = False
    if item.name_es and not target.name_es and target.name == item.name:
        target.name_es, inherited = item.name_es, True
    if item.composition_es and not target.composition_es and target.composition == item.composition:
        target.composition_es, inherited = item.composition_es, True
    if sibling.get("name_es") and not target.store_color_es:
        target.store_color_es, inherited = sibling["name_es"], True
    if inherited:
        db.commit()
    if _foreign(target.store, target.url) and not target.translated:
        translate_soon([target.id])
    return target


def _seasons_clash(a: outfits.Item, b: outfits.Item) -> bool:
    """¿Es una de invierno y la otra de verano? De verano es también lo que Hoy solo propone de mayo a
    septiembre aunque esté marcado «todo el año»: una camiseta no es pareja para un abrigo."""
    return (a.season == "invierno" and outfits.summer_only(b)) or (b.season == "invierno" and outfits.summer_only(a))


def matches(db: Session, item: ShopItem) -> tuple[int, list[tuple[str, list[tuple[Garment, int]]]]]:
    """«Combina con…»: las prendas del armario con las que mejor va un producto de tienda.

    Devuelve cuántas prendas hay en el armario y, por cada parte del cuerpo que no es la suya, las
    `MATCH_PER_GROUP` con mejor afinidad (prenda, afinidad), de mayor a menor. Es la misma cuenta que
    hace `score` para «Combina con N de tus prendas»: la afinidad de la pareja con lo aprendido en
    Gustos; aquí entra todo lo que llega a MATCH_MIN. Respeta las reglas del usuario: cazadora o
    sobrecamisa sobre sudadera con cremallera entera, no; y no se mezcla verano con invierno, contando
    como de verano lo mismo que en Hoy (pantalón corto, manga corta, camisetas y polos).
    """
    from ..routers.taste import load_taste  # aquí, para no atar el servicio a los routers al importar

    garments = list(db.scalars(select(Garment)))
    candidate = candidate_item(item)
    taste = load_taste(db)
    found: dict[str, list[tuple[Garment, int]]] = {}
    for garment in garments:
        piece = wardrobe_item(garment)
        if piece.category == candidate.category or _seasons_clash(candidate, piece):
            continue
        if style_rules.zip_clash(candidate, piece) or style_rules.zip_clash(piece, candidate):
            continue
        affinity = outfits.combo_affinity([candidate, piece], taste)
        if affinity >= MATCH_MIN:
            found.setdefault(garment.category, []).append((garment, affinity))
    groups = [
        (category, sorted(found[category], key=lambda pair: (-pair[1], not pair[0].favorite, pair[0].id))[:MATCH_PER_GROUP])
        for category in catalog.CATEGORIES
        if category in found
    ]
    return len(garments), groups


def _lookup(db: Session, query: str, today: date) -> list[ShopItem]:
    started = time.monotonic()
    clean_lookups(db)
    found = _search_stores(query)
    context = Context.load(db)
    items: list[ShopItem] = []
    down: list[str] = []
    for connector, product in found:
        row = db.scalars(select(ShopItem).where(ShopItem.product_ref == product.product_ref)).first()
        if row is not None and (already(db, row) or (row.status in (NEW, SEARCHED) and _has_photos(row))):
            if row.status == SEARCHED:
                row.first_seen_at = now_utc()  # se ha vuelto a buscar: el plazo empieza otra vez
                db.commit()
            items.append(row)
            continue
        if time.monotonic() - started > LOOKUP_SECONDS:
            break
        try:
            detail = connector.detail(product.store_data)
            if detail is None or not detail.photo_urls:
                continue  # sin foto de producto no hay nada que guardar ni que analizar
            photos = _save_photos(connector, detail.photo_urls)
        except Exception as exc:
            if isinstance(exc, ShopError):
                down.append(f"{connector.name} no responde ahora ({exc})")
            else:
                log.exception("Compras: error inesperado al buscar %s", product.product_ref)
                down.append(f"No se pudo traer «{product.name}»: error inesperado")
            continue
        items.append(_store_fetched(db, row, product, detail, photos, today, context))
    if not items:
        if down:
            raise LookupFailed(down[0], "tienda")
        raise LookupFailed("Lo he encontrado, pero la tienda no tiene fotos de producto: no lo puedo guardar")
    log.info("Compras: búsqueda de «%s» (%s resultados, %.1f s)", query[:60], len(items), time.monotonic() - started)
    return items


# ---------- El buscador en lo guardado (el catálogo entero de la última consulta)

_ANY_LINK = re.compile(r"(?:https?://|www\.)\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}/\S*", re.IGNORECASE)
_LOOKUP_SKIP = {"de", "la", "el", "en", "con", "para", "the", "and", "pour", "avec", "les", "des", "du", "le"}


def _alnum(value) -> str:
    return re.sub(r"[^a-z0-9]", "", norm(str(value or ""))).lstrip("0")


def _codes(row: ShopItem) -> set[str]:
    """Las referencias de un producto, en minúsculas y sin separadores ni ceros delante: la de la tienda
    (3918/300/800), el código de fabricante (IF6490), la de sus fotos (807022), el id de Zara…"""
    data = row.store_data or {}
    values = [store_reference(row), data.get("model"), data.get("ref"), data.get("seo_id"), data.get("sku"),
              data.get("mpn"), data.get("pid"), data.get("handle"), row.maker_code]
    snap = data.get("snap")
    if isinstance(snap, dict):
        values.append(snap.get("ref"))
    return {code for code in map(_alnum, values) if len(code) >= 4}


def _link_match(url: str):
    """De un enlace de producto a cómo reconocerlo entre lo guardado: una función fila -> bool, o None si
    no es un enlace de producto de una tienda conocida."""
    parts = urlsplit(url if "://" in url else f"https://{url}")
    host, path = (parts.hostname or "").lower(), parts.path
    query = parse_qs(parts.query)
    first = lambda key: (query.get(key) or [""])[0]  # noqa: E731
    if "jdsports." in host and (m := re.search(r"/product/[^/]+/(\d{5,10})", path)):
        return lambda row, ref=f"jdsports:{m.group(1)}": row.product_ref == ref
    if host.endswith("courir.com") and (m := re.search(r"-(\d{6,8})\.html", path)):
        return lambda row, ref=f"courir:{m.group(1)}": row.product_ref == ref
    if host.endswith("zara.com") and (m := re.search(r"-p(\d{7,8})", path)):
        seo, v1 = m.group(1).zfill(8), first("v1")
        return lambda row: row.store == "zara" and str((row.store_data or {}).get("seo_id")) == seo and (
            not v1 or str((row.store_data or {}).get("discern_id")) == v1)
    if host.endswith("pullandbear.com") and first("pelement"):
        bundle, color = first("pelement"), first("cS")
        return lambda row: row.store == "pullandbear" and str((row.store_data or {}).get("bundle")) == bundle and (
            not color or str((row.store_data or {}).get("color")) == color)
    if host.endswith("bershka.com") and (m := re.search(r"c0p(\d+)\.html", path)):
        bundle, color = m.group(1), first("colorId")
        return lambda row: row.store == "bershka" and str((row.store_data or {}).get("bundle")) == bundle and (
            not color or str((row.store_data or {}).get("color")) == color)
    if host.endswith("snipes.com") and (m := re.search(r"/p/[a-z0-9-]+?-(\d{2,9})/?$", path)):
        return lambda row, ref=f"snipes:{m.group(1)}": row.product_ref == ref
    if ("sizeofficial." in host or host.endswith("size.co.uk")) and (m := re.search(r"/products/([A-Za-z0-9-]+)", path)):
        return lambda row, ref=f"size:{m.group(1)}": row.product_ref == ref
    if "footlocker." in host and (m := re.search(r"/(\d{12})\.html", path)):
        return lambda row, ref=f"footlocker:{m.group(1)}": row.product_ref == ref
    if host.endswith("jules.com") and (m := re.search(r"/p/(\d{6,20})\.html", path)):
        return lambda row, ref=f"jules:{m.group(1)}": row.product_ref == ref
    if host.endswith("bonoboplanet.com") and (m := re.search(r"-(\d{12,20})\.html", path)):
        return lambda row, ref=f"bonobo:{m.group(1)}": row.product_ref == ref
    return None


def saved_matches(db: Session, query: str) -> list[ShopItem]:
    """Lo guardado que encaja con lo que se busca (sin preguntar a ninguna tienda): por enlace de
    producto, por referencia o código de fabricante, o por las palabras del nombre (el de la tienda o el
    traducido), la marca o el color. De mejor a peor nota, como mucho LOOKUP_MAX."""
    rows = list(db.scalars(select(ShopItem).where(ShopItem.store.in_(list(shops.CONNECTORS)))))
    link = _ANY_LINK.search(query)
    if link:
        match = _link_match(link.group().rstrip(".,;)"))
        found = [row for row in rows if match(row)] if match else []
    else:
        bare = re.sub(r"\b(ref|r[ée]f[ée]rence|referencia|code|mod[eè]le|modelo|style)\b\.?:?", " ", query, flags=re.I)
        code = _alnum(bare)
        if re.search(r"\d", code) and len(code) >= 4 and not re.search(r"[^\W\d_]{3,}\s+[^\W\d_]{3,}", bare):
            # Tiene forma de referencia: «3918/300», «03918300», «IF6490», «DD1391-100».
            found = [row for row in rows if any(c.startswith(code) for c in _codes(row))]
        else:
            words = [w for w in re.findall(r"[a-z0-9]+", norm(query)) if len(w) >= 3 and w not in _LOOKUP_SKIP]
            if not words:
                return []
            found = []
            for row in rows:
                text = norm(" ".join(filter(None, (
                    row.name, row.name_es, row.brand, row.store_color, row.store_color_es, store_reference(row),
                ))))
                if all(word in text for word in words):
                    found.append(row)
    if not found:
        return []
    context = Context.load(db)
    # Primero lo ya guardado y con fotos; después, por nota.
    ranked = sorted(found, key=lambda row: (not already(db, row), -context.score(row)[0], row.id))
    return ranked[:LOOKUP_MAX]


def _lookup_saved(db: Session, query: str, today: date) -> list[ShopItem]:
    """El buscador mira primero en lo guardado. Lo que ya tiene fotos se devuelve tal cual; a lo demás
    (un candidato del catálogo, algo descartado o caducado) se le baja la ficha y las fotos como en el
    buscador normal. Si es de una tienda de navegador y el listado no guardó lo necesario, sale sin foto
    (`photos` vacío): se bajan en segundo plano en cuanto se pueda (ver `fetch_missing_photos`).
    [] si no hay nada guardado que encaje: entonces se pregunta a las tiendas."""
    found = saved_matches(db, query)
    if not found:
        return []
    started = time.monotonic()
    context = Context.load(db)
    items: list[ShopItem] = []
    for row in found:
        if already(db, row) or (row.status in (NEW, SEARCHED, VARIANT) and _has_photos(row)):
            if row.status == SEARCHED:
                row.first_seen_at = now_utc()
                db.commit()
            items.append(row)
            continue
        if time.monotonic() - started > LOOKUP_SECONDS:
            break
        before = row.status
        connector = shops.CONNECTORS[row.store]
        try:
            detail = _detail_for(row, offline=True)
            photos = _save_photos(connector, detail.photo_urls) if detail is not None and detail.photo_urls else []
        except Exception as exc:
            if not isinstance(exc, ShopError):
                log.exception("Compras: error inesperado al traer %s de lo guardado", row.product_ref)
            continue
        if detail is not None and not photos:
            continue  # sin foto de producto no hay nada que guardar
        if detail is None and not shops.needs_browser(row.store):
            continue  # ya no está en la tienda
        if detail is None:
            detail = shops.ShopDetail(price_cents=None, sizes=row.sizes or [], photo_urls=[])
        items.append(_mark_searched(db, row, before, detail, photos, context, today))
    log.info("Compras: búsqueda en lo guardado de «%s» (%s resultados)", query[:60], len(items))
    return items


# ---------- Traducción al español (lo que se enseña de las tiendas en otro idioma)

TRANSLATE_STATUSES = (NEW, LIKED, SEARCHED, VARIANT)
LOOKUP_TRANSLATE_SECONDS = 15.0  # lo que el buscador espera a la traducción antes de responder
_translating = threading.Lock()


# Productos guardados de la tienda española (antes de pasar a la de Francia): ya están en español.
_SPANISH_URL = re.compile(r"zara\.com/es/|jdsports\.es/")


def _foreign(store: str, url: str | None = None) -> bool:
    connector = shops.CONNECTORS.get(store)
    if url and _SPANISH_URL.search(url):
        return False
    return connector is not None and getattr(connector, "language", "es") != "es"


def translate_items(db: Session, ids: list[int] | None = None) -> int:
    """Traduce nombre, color y composición de lo que se enseña y aún no está traducido (de las
    tiendas que no están en español). Lo original no se toca: la nota se hace siempre con él.
    Devuelve cuántos productos se han traducido. Si la IA falla, no pasa nada: se queda el original y
    se vuelve a intentar la próxima vez."""
    from .ai import translate  # aquí: el servicio de Compras no necesita la IA para nada más

    stmt = select(ShopItem).where(ShopItem.status.in_(TRANSLATE_STATUSES), ShopItem.translated.is_not(True))
    if ids is not None:
        stmt = stmt.where(ShopItem.id.in_(ids))
    items = [item for item in db.scalars(stmt) if _foreign(item.store, item.url)]
    if not items:
        return 0
    texts = [t for item in items for t in (item.name, item.store_color, item.composition) if t]
    # Los nombres de los otros colores (los circulitos), en el mismo lote.
    texts += [s["name"] for item in items for s in item.siblings or [] if s.get("name") and not s.get("name_es")]
    done = translate.translate(texts)
    if not done:
        return 0

    def key(text: str | None) -> str:
        return " ".join((text or "").split())[: translate.MAX_TEXT]

    count = 0
    for item in items:
        name = done.get(key(item.name))
        if not name:
            continue  # sin nombre traducido no se da por hecho: se reintenta
        item.name_es = name[:160]
        item.store_color_es = done.get(key(item.store_color), item.store_color_es or None) if item.store_color else None
        item.composition_es = done.get(key(item.composition)) if item.composition else None
        if item.siblings:
            item.siblings = [
                {**s, "name_es": done[key(s["name"])]} if not s.get("name_es") and done.get(key(s.get("name"))) else s
                for s in item.siblings
            ]
        item.translated = True
        count += 1
    db.commit()
    return count


def _translate_job(ids: list[int] | None = None) -> None:
    if not _translating.acquire(blocking=False):
        return  # ya hay una traducción en marcha: lo que quede se traduce la próxima vez
    try:
        with SessionLocal() as db:
            translate_items(db, ids)
    except Exception:
        log.exception("Compras: la traducción falló")
    finally:
        _translating.release()


def translate_soon(ids: list[int] | None = None) -> threading.Thread | None:
    """Traduce en un hilo aparte, sin hacer esperar a nadie. None si está desactivado (tests)."""
    if not config.SHOP_TRANSLATE:
        return None
    worker = threading.Thread(target=_translate_job, args=(ids,), name="armario-traduccion", daemon=True)
    worker.start()
    return worker


# ---------- En segundo plano
#
# Dos clases de trabajo, cada uno con su cerrojo:
# - La consulta del catálogo (`start_refresh`): de noche, larga (media hora o más por tienda). Una a la
#   vez. Se puede cancelar desde el panel y deja su avance en `crawl_progress()`.
# - Los trabajos cortos (`_lock`): «Ver más» y la reserva (fotos por adelantado). La consulta coge este
#   mismo cerrojo solo para su parte final (bajar las propuestas), para no pisarse con ellos.
# El buscador va aparte (`_lookup_lock`): no lo frena una consulta en marcha.

_lock = threading.Lock()  # un trabajo corto a la vez: «Ver más» o la reserva
_lookup_lock = threading.Lock()  # una búsqueda a la vez
_running = threading.Event()  # hay un «Ver más» en marcha (la reserva no se enseña)
_stop = threading.Event()
_worker: threading.Thread | None = None
_scheduler: threading.Thread | None = None
_job = "mas"  # qué trabajo corto está en marcha: un ver «mas», la «reserva» o las «fotos» que faltan
_reserve_filter: dict | None = None  # la reposición en marcha es la de este filtro de Descubrir
_photos_wanted = threading.Event()  # se han pedido las fotos que faltan y aún no se ha lanzado el trabajo

_crawl_lock = threading.Lock()
_crawl_running = threading.Event()
_crawl_cancel = threading.Event()
_crawl_progress: dict = {}
_crawl_worker: threading.Thread | None = None

# El bucle mira cada pocos minutos si a alguna tienda le toca su consulta de la noche (o si toca reponer).
FIRST_CHECK_SECONDS, CHECK_EVERY_SECONDS = 30, 300


def is_running() -> bool:
    """¿Hay una consulta del catálogo o un «Ver más» en marcha?"""
    return _crawl_running.is_set() or _running.is_set()


def running_job() -> str | None:
    """«mas» mientras hay un «Ver más» en marcha; si no, «consulta» mientras se recorre el catálogo."""
    if _running.is_set():
        return "mas"
    return "consulta" if _crawl_running.is_set() else None


def crawl_progress() -> dict | None:
    """Por dónde va la consulta en marcha (para el panel): tienda, sección, páginas y productos leídos,
    si es la de la noche y si se está cancelando. None si no hay ninguna."""
    if not _crawl_running.is_set():
        return None
    return {**_crawl_progress, "cancelling": _crawl_cancel.is_set()}


def _crawling_stores() -> set[str]:
    """La tienda cuyo catálogo se está recorriendo ahora: mientras tanto, la reserva no la toca."""
    store = _crawl_progress.get("store") if _crawl_running.is_set() else None
    return {store} if store else set()


def _run_locked(job, kind: str) -> None:
    """Hace el trabajo corto (`job(db)`) con el cerrojo ya cogido y lo suelta al acabar, pase lo que
    pase. Después, aparte y sin cerrojo, traduce lo nuevo: las propuestas salen ya, en el idioma de la
    tienda, y pasan al español en cuanto llega la traducción. «Ver más» puede abrir el navegador; la
    reserva no (solo usa lo que guardó el listado)."""
    try:
        with SessionLocal() as db:
            if kind in ("mas", "fotos"):
                with shops.browser.session():
                    job(db)
            else:
                job(db)
    except Exception:
        log.exception("Compras: el trabajo «%s» falló", kind)
    finally:
        global _reserve_filter
        _reserve_filter = None
        _running.clear()
        _lock.release()
    translate_soon()
    if kind != "fotos" and _photos_wanted.is_set():
        photos_soon()  # alguien pidió fotos mientras este trabajo tenía el cerrojo


def refilling() -> dict | None:
    """Si está en marcha la reposición de un filtro que se quedó vacío: {"store", "category"}."""
    return dict(_reserve_filter) if _reserve_filter and _lock.locked() and _job == "reserva" else None


def _start(job, kind: str) -> bool:
    global _worker, _job
    if not _lock.acquire(blocking=False):
        return False
    _job = kind
    if kind == "mas":
        _running.set()
    _worker = threading.Thread(target=_run_locked, args=(job, kind), name=f"armario-compras-{kind}", daemon=True)
    _worker.start()
    return True


def _run_crawl(stores: list[str] | None, night: bool) -> None:
    try:
        # El navegador (Pull&Bear, Bershka, JD Sports) solo puede abrirse aquí dentro y se cierra al acabar.
        with SessionLocal() as db, shops.browser.session():
            refresh(db, stores=stores, night=night, cancel=_crawl_cancel, progress=_crawl_progress)
    except Exception:
        log.exception("Compras: la consulta falló")
    finally:
        _crawl_running.clear()
        _crawl_lock.release()
    translate_soon()
    top_up_soon(force=True)  # los colores de las propuestas nuevas y lo que falte en la reserva
    if _photos_wanted.is_set():
        photos_soon()  # si la reserva tiene el cerrojo, se lanza cuando acabe (ver `_run_locked`)


def start_refresh(stores: list[str] | None = None, night: bool = False) -> bool:
    """Lanza la consulta del catálogo en un hilo aparte y vuelve ya. `night`: la automática, con las
    pausas largas. False si ya había una en marcha."""
    global _crawl_worker
    if not _crawl_lock.acquire(blocking=False):
        return False
    _crawl_cancel.clear()
    _crawl_progress.clear()
    _crawl_running.set()
    _crawl_worker = threading.Thread(target=_run_crawl, args=(stores, night), name="armario-compras-consulta",
                                     daemon=True)
    _crawl_worker.start()
    return True


def cancel_refresh() -> bool:
    """Corta la consulta en marcha (en la siguiente página): lo leído se guarda y se retoma la próxima
    vez. False si no había ninguna."""
    if not _crawl_running.is_set():
        return False
    _crawl_cancel.set()
    return True


def start_more(store: str | None = None, category: str | None = None, only: ShopFilter | None = None) -> bool:
    """Lanza un «Ver más» en un hilo aparte y vuelve ya. False si ya había un trabajo corto en marcha."""
    return _start(lambda db: more(db, store, category, only=only), "mas")


def photos_soon() -> bool:
    """Lanza en segundo plano el trabajo que baja las fotos que faltan en lo guardado (`fetch_missing_photos`),
    si hay algo que bajar. Solo con el bucle automático encendido (`ARMARIO_SHOP_AUTO=0`: nada). Si hay otro
    trabajo corto en marcha, queda pedido y se lanza al acabar ese; con una consulta del catálogo en marcha,
    al acabar la consulta (no se abre un segundo navegador ni se le pisa). False si no se lanza ahora."""
    if not config.SHOP_AUTO:
        return False
    _photos_wanted.set()
    if _crawl_running.is_set():
        return False
    try:
        with SessionLocal() as db:
            if not missing_photos(db):
                _photos_wanted.clear()
                return False
    except Exception:
        log.exception("Compras: no se pudo mirar qué fotos faltan")
        return False
    if _start(lambda db: fetch_missing_photos(db, stop=_crawl_running.is_set), "fotos"):
        _photos_wanted.clear()
        return True
    return False


def photos_running() -> bool:
    """¿Está en marcha el trabajo de las fotos que faltan (con el navegador quizá abierto)?"""
    return _lock.locked() and _job == "fotos"


def top_up_soon(force: bool = False, store: str | None = None, category: str | None = None,
                only: ShopFilter | None = None) -> bool:
    """Repone la reserva en segundo plano si hace falta (o siempre, con `force`; o de un filtro que se
    ha quedado vacío, con `store`/`category`). Solo con el bucle automático encendido (en los tests y
    en desarrollo, `ARMARIO_SHOP_AUTO=0`, no hace nada). False si no se lanza (otro trabajo en marcha:
    el bucle lo vuelve a intentar en unos minutos)."""
    if not config.SHOP_AUTO:
        return False
    only = only or ShopFilter.of(store, category)
    if not only.empty:
        def job(db):
            global _reserve_filter
            _reserve_filter = only.as_dict()
            top_up(db, only=only)

        return _start(job, "reserva")
    if not force:
        try:
            with SessionLocal() as db:
                if not needs_top_up(db):
                    return False
        except Exception:
            log.exception("Compras: no se pudo mirar la reserva")
            return False
    return _start(lambda db: top_up(db), "reserva")


def wait_idle(timeout: float = 30) -> None:
    """Espera a que terminen los trabajos en marcha (para los tests)."""
    for worker in (_crawl_worker, _worker):
        if worker is not None:
            worker.join(timeout)


def _loop() -> None:
    delay = FIRST_CHECK_SECONDS
    while not _stop.wait(delay):
        delay = CHECK_EVERY_SECONDS
        try:
            with SessionLocal() as db:
                clean_lookups(db)
                # Como mucho dos tiendas por noche y una pesada: las demás, la noche siguiente. Si se están
                # bajando las fotos que faltan (con el navegador), la consulta espera a la vuelta siguiente.
                due = [] if _crawl_running.is_set() or photos_running() else tonight(db)
            translate_soon()  # lo que se quedara sin traducir (la IA falló o estaba ocupada)
            if due:
                if start_refresh(due, night=True):
                    with SessionLocal() as db:
                        note_tonight(db, due)
            else:
                top_up_soon()
                photos_soon()  # lo guardado sin foto (si la reserva está en marcha, va detrás)
        except Exception:
            log.exception("Compras: fallo en el bucle de las consultas")


def start_scheduler() -> None:
    """El bucle que arranca con la app: cada pocos minutos mira si a alguna tienda le toca su consulta
    (su día, a la hora de la noche, o en cuanto arranque si estaba apagada) y si hay que reponer."""
    global _scheduler
    if _scheduler is not None and _scheduler.is_alive():
        return
    _stop.clear()
    _scheduler = threading.Thread(target=_loop, name="armario-compras", daemon=True)
    _scheduler.start()


def stop_scheduler() -> None:
    _stop.set()
    _crawl_cancel.set()
