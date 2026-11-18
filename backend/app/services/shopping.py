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
"""
import json
import logging
import math
import re
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import catalog, config
from ..db import SessionLocal
from ..models import Garment, Setting, ShopItem, now_utc
from . import ai, outfits, shops, storage, style_rules
from .ai.base import build_prompt
from .shops import ShopError
from .shops.estimate import norm

log = logging.getLogger("armario.compras")

# «candidato»: está en el catálogo de la tienda pero no se ha enseñado (no tiene fotos).
CANDIDATE = "candidato"
NEW, LIKED, DISCARDED, BOUGHT, EXPIRED = "nuevo", "gustado", "descartado", "comprado", "caducado"

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
    r"jacquard|rejilla|leopardo|balloon|pareo|kimono|plumas)\b"
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
    return [slug for slug in connector.categories if slug in chosen]


def set_store(db: Session, store: str, enabled: bool | None, categories: list[str] | None) -> None:
    if enabled is not None:
        stores = set(enabled_stores(db))
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


def is_due(db: Session, store: str, today: date | None = None) -> bool:
    """¿Toca consultar esta tienda hoy?

    Sí, si está activada y desde su último día de consulta no hay ninguna consulta que fuera bien (hoy es
    su día, o lo fue mientras la app estaba apagada). Si la de hoy ya falló, no se insiste hasta mañana.
    """
    today = today or outfits.local_today()
    if store not in enabled_stores(db):
        return False
    status = store_status(db, store) or {}
    ok_day = _parse_day(status.get("ok_day"))
    if ok_day and ok_day >= check_day(store, today):
        return False
    return _parse_day(status.get("day")) != today


def due_stores(db: Session, today: date | None = None) -> list[str]:
    return [store for store in enabled_stores(db) if is_due(db, store, today)]


def next_check(db: Session, store: str, today: date | None = None) -> date:
    """Qué día se consultará la tienda por su cuenta: hoy si toca, mañana si hoy falló, o su próximo día."""
    today = today or outfits.local_today()
    status = store_status(db, store) or {}
    ok_day = _parse_day(status.get("ok_day"))
    if ok_day and ok_day >= check_day(store, today):
        return check_day(store, today) + timedelta(days=7)
    return today + timedelta(days=1) if _parse_day(status.get("day")) == today else today


# ---------- Lo aprendido en la pestaña


_STOP_WORDS = {
    "con", "sin", "para", "por", "del", "los", "las", "the", "and", "zara", "hombre", "fit", "regular", "manga",
    "mangas", "larga", "corta", "basico", "basica", "pack", "edition", "cuello", "efecto", "tejido",
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

    def learn(self, item, liked: bool, reason: str | None = None, strength: float = 1.0) -> None:
        """Un «me gusta» cuenta entero en todo (por `strength`: una compra vale varias veces más).
        Un «no me gusta» carga la culpa según el motivo (`_BLAME`)."""
        blame = (1.0, 1.0, 1.0, 1.0) if liked else _BLAME.get(reason, _BLAME[None])
        by_type, by_color, by_price, by_word = (strength * part for part in blame)
        votes = [
            (self.types, item.type, by_type),
            (self.colors, item.color, by_color),
            (self.prices, price_band(item.price_cents), by_price),
        ]
        votes += [(self.words, word, by_word) for word in name_words(item.name)]
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
    for item in db.scalars(select(ShopItem).where(ShopItem.status.in_((LIKED, DISCARDED, BOUGHT, EXPIRED)))):
        if item.status == BOUGHT:
            learned.learn(item, True, strength=BOUGHT_WEIGHT)
        elif item.status == LIKED:
            learned.learn(item, True)
        elif item.liked_at is not None:  # gustó, pero caducó o lo quitó sin comprarlo
            learned.learn(item, True, strength=LAPSED_WEIGHT)
        elif item.status == DISCARDED:
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
_SUMMER_TEXT = re.compile(r"\b(tirantes|sin mangas|lino|bermudas?|shorts?|banador|sandalias?|chanclas?)\b")
_SHORT_SLEEVE, _LONG_SLEEVE = re.compile(r"\bmangas? cortas?\b"), re.compile(r"\bmangas? largas?\b")


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
    """La nota de un producto contra el armario (0-100) y los motivos, legibles, a favor y en contra."""
    candidate = candidate_item(product)
    reasons: list[dict] = []
    total = BASE

    def reason(text: str, kind: str = "pro") -> None:
        reasons.append({"text": text, "kind": kind})

    # 1. Lo que el usuario ha ido diciendo en la tienda: lo que más pesa.
    if prefs is not None:
        plural, feminine = _TYPE_FORMS[candidate.type]
        article = "las" if feminine else "los"
        by_type = prefs.opinion(prefs.types, candidate.type)
        by_color = prefs.opinion(prefs.colors, candidate.color)
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
    if wardrobe:
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
    same = sum(1 for g in same_type if g.color == candidate.color)
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


def like(db: Session, item: ShopItem) -> None:
    now = now_utc()
    item.status = LIKED
    item.liked_at = item.decided_at = now
    item.expires_at = now + timedelta(days=LIKED_DAYS)
    item.can_undo = True
    db.commit()
    rescore_pending(db)


def dislike(db: Session, item: ShopItem) -> None:
    """No se vuelve a proponer. Las fotos se quedan mientras se pueda deshacer con «Volver»: se borran
    en la siguiente consulta semanal de su tienda (`_close_undo`)."""
    item.status = DISCARDED
    item.decided_at = now_utc()
    item.discard_reason = None
    item.can_undo = True
    db.commit()
    rescore_pending(db)


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


class CannotBuy(Exception):
    pass


def buy(db: Session, item: ShopItem, size: str | None, preferred_provider: str) -> tuple[Garment, bool]:
    """Pasa el producto al armario con las fotos de la tienda. Devuelve la prenda y si la analizó la IA.

    Es el único momento en que se usa la IA: el mismo análisis que al añadir una prenda a mano. Si falla,
    la prenda se crea igualmente con los campos estimados sin IA.
    """
    photos = [p for p in (item.photos or []) if storage.exists(p)]
    if not photos:
        raise CannotBuy("Las fotos de este producto ya no están; no se puede pasar al armario")
    in_stock = [s["name"] for s in item.sizes or [] if s.get("in_stock")]
    if size and in_stock and size not in in_stock:
        raise CannotBuy("Esa talla no está entre las disponibles")
    front, back, extra = (photos + [None, None])[:3]

    result = ai.analyze(
        [storage.photo_path(p) for p in photos[:3]],
        preferred=preferred_provider,
        prompt=build_prompt(
            has_back=bool(back), has_label=False, has_extra=bool(extra),
            kind="calzado" if item.category == "calzado" else "ropa",
        ),
    )
    brand = shops.CONNECTORS[item.store].name if item.store in shops.CONNECTORS else item.store.capitalize()
    draft = result.draft
    if draft is not None:
        # La marca y la talla no salen de la foto: son la tienda y la talla elegida.
        saved_draft = {**draft.model_dump(), "brand": brand, "size": size}
        fields = dict(
            name=draft.name.strip(), type=draft.type, color_primary=draft.color_primary.name,
            color_primary_hex=draft.color_primary.hex.lower(),
            colors_secondary=[c.model_dump() for c in draft.colors_secondary],
            pattern=draft.pattern, style=draft.style, closure=draft.closure, hood=draft.hood, fit=draft.fit,
            thickness=draft.thickness, details=draft.details.strip(), season=draft.season,
            notes=draft.notes.strip(), ai_provider=result.provider, ai_confidence=draft.confidence,
            ai_draft=saved_draft,
        )
    else:
        saved_draft = None
        fields = dict(
            name=item.name[:120], type=item.type, color_primary=item.color,
            color_primary_hex=item.store_color_hex or catalog.COLOR_HEX[item.color], colors_secondary=[],
            pattern=item.pattern, style=item.style, details="", season=item.season, notes="",
        )

    garment = Garment(
        **fields,
        category=catalog.category_of(fields["type"]),
        brand=brand,
        size=size,
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


def _varied(entries: list[tuple], head: int) -> list[tuple]:
    """Ordena por nota, pero sin amontonar lo mismo: cada elegido baja un poco (solo para elegir) a los
    que quedan de su mismo tipo y color y de su misma categoría de la tienda. Así una categoría floja
    no entra a la fuerza y una buena no lo llena todo. Solo se afina la cabeza (`head`): el resto va por nota.
    """
    left = sorted(entries, key=lambda entry: (-entry[0], entry[2].product_ref))
    picked: list[tuple] = []
    same: dict[tuple, int] = {}
    sections: dict[str, int] = {}
    while left and len(picked) < head:
        def worth(entry: tuple) -> float:
            row = entry[2]
            return entry[0] - REPEAT_STEP * same.get((row.type, row.color), 0) - SECTION_STEP * sections.get(row.section, 0)

        best = max(range(len(left)), key=lambda i: (worth(left[i]), -i))
        entry = left.pop(best)
        row = entry[2]
        same[(row.type, row.color)] = same.get((row.type, row.color), 0) + 1
        sections[row.section] = sections.get(row.section, 0) + 1
        picked.append(entry)
    return picked + left


def _ranked(context: "Context", rows: list[ShopItem], head: int) -> list[tuple]:
    """Los candidatos en el orden en que se intentará traerlos, como (nota, motivos, fila).

    El cupo se reparte a partes iguales entre tiendas, para que un catálogo grande no entierre a los
    demás, y dentro de cada tienda manda la nota con algo de variedad (`_varied`). Es el orden de
    traída: al enseñarlas, las propuestas van por nota, vengan de la tienda que vengan.
    """
    by_store: dict[str, list[tuple]] = {}
    for row in rows:
        value, reasons = context.score(row)
        by_store.setdefault(row.store, []).append((value, reasons, row))
    return list(_round_robin([_varied(entries, head) for entries in by_store.values()]))


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
    row.name, row.price_cents, row.url = name, product.price_cents, product.url
    row.store_color, row.section, row.store_data = product.store_color[:60], product.section, product.store_data
    row.type, row.category, row.color = product.type, product.category, product.color
    row.pattern, row.style = product.pattern, product.style
    if not described:
        row.season, row.details = product.season, product.details
    row.last_checked_at = None  # todavía no se le ha pedido la ficha esta semana
    return row


def candidates_left(db: Session, today: date | None = None, store: str | None = None,
                    category: str | None = None) -> list[ShopItem]:
    """Los candidatos que «Ver más» aún puede traer: de las tiendas activadas (o de una), de una categoría
    si se filtra, de temporada y sin haber fallado ya esta semana al pedir su ficha."""
    today = today or outfits.local_today()
    stores = [s for s in enabled_stores(db) if store in (None, s)]
    stmt = select(ShopItem).where(
        ShopItem.status == CANDIDATE, ShopItem.store.in_(stores), ShopItem.last_checked_at.is_(None)
    )
    if category:
        stmt = stmt.where(ShopItem.category == category)
    return [row for row in db.scalars(stmt) if not out_of_season(row, today)]


def _promote(db: Session, context: "Context", ranked: list[tuple], limit: int, today: date, failed) -> list[float]:
    """Baja la ficha y las fotos de los mejores candidatos hasta tener `limit` propuestas nuevas, y
    devuelve sus notas. Si uno no sirve (ya no existe, sin foto, sin tallas o, leída la descripción,
    fuera de temporada) entra el siguiente, con un tope de peticiones por educación con la tienda.
    """
    scores: list[float] = []
    attempts = 0
    for _value, _reasons, row in ranked:
        if len(scores) >= limit or attempts >= limit * 2:
            break
        attempts += 1
        connector = shops.CONNECTORS[row.store]
        try:
            detail = connector.detail(row.store_data)
            row.last_checked_at = now_utc()
            if detail is None or not detail.photo_urls or not detail.in_stock:
                db.commit()
                continue  # ya no existe, no tiene foto de producto o no queda ninguna talla
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
            failed(row.name, exc)
            row.last_checked_at = None  # un fallo de red no dice nada del producto: se podrá reintentar
            db.commit()
            continue
        row.status, row.batch, row.photos = NEW, today, photos
        row.price_cents = detail.price_cents or row.price_cents
        row.store_color_hex, row.sizes, row.in_stock = detail.color_hex, detail.sizes, True
        row.first_seen_at = now_utc()
        row.score, row.reasons = context.score(row)  # con la descripción ya leída
        db.commit()
        scores.append(row.score)
    return scores


def _failure_log(result: dict):
    """Devuelve la función que apunta un fallo en `result` («Camisas: HTTP 403»)."""

    def failed(what: str, exc: Exception) -> None:
        message = str(exc) if isinstance(exc, ShopError) else "error inesperado en el conector"
        result["failed"] += 1
        result["errors"].append(f"{what}: {message}")

    return failed


def refresh_store(db: Session, store: str, today: date | None = None, limit: int | None = None) -> dict:
    """Consulta UNA tienda: guarda su catálogo como candidatos, deja los mejores como propuestas y
    revisa sus «me gusta».

    Nunca lanza por culpa de la tienda: lo que falla se apunta, se guarda en el estado de la tienda
    (`store_status`) y se sigue con lo demás.
    """
    now = now_utc()
    today = today or outfits.local_today()
    # El cupo de la tanda se reparte entre las tiendas activadas.
    limit = math.ceil((config.SHOP_BATCH_SIZE if limit is None else limit) / max(1, len(enabled_stores(db))))
    connector = shops.CONNECTORS[store]
    previous = store_status(db, store) or {}
    result = {
        "at": now.isoformat(), "day": today.isoformat(), "ok": False, "ok_day": previous.get("ok_day"),
        "found": 0, "added": 0, "expired": 0, "failed": 0, "error": None, "errors": [],
    }
    errors: list[str] = result["errors"]
    failed = _failure_log(result)

    # Se apunta ya el intento: si el proceso muere a medias, hoy no se vuelve a insistir.
    _save_status(db, store, {**previous, "day": today.isoformat()})
    db.commit()

    # Lo que ya se enseñó alguna vez (sea cual sea su estado) no vuelve; los candidatos se renuevan.
    shown = set(db.scalars(select(ShopItem.product_ref).where(ShopItem.status != CANDIDATE)))
    old = {
        row.product_ref: row
        for row in db.scalars(select(ShopItem).where(ShopItem.store == store, ShopItem.status == CANDIDATE))
    }
    fresh: dict[str, ShopItem] = {}

    # 1. Listados: una petición por categoría. Solo datos del listado, sin fotos ni detalle.
    active = active_categories(db, store)
    listed: set[str] = set()
    for slug in active:
        label = connector.categories.get(slug, slug)
        try:
            products = connector.list_category(slug)
        except Exception as exc:  # ni la tienda ni un conector roto pueden tumbar la tanda
            if not isinstance(exc, ShopError):
                log.exception("Compras: error inesperado en %s/%s", store, slug)
            failed(label, exc)
            continue
        result["ok"] = True
        result["found"] += len(products)
        listed.add(slug)
        for product in products:
            ref = product.product_ref
            if ref not in shown and ref not in fresh:  # la misma prenda puede salir en dos categorías
                fresh[ref] = _store_candidate(db, old.get(ref), product, today)

    if result["ok"]:
        # 2. Fuera lo que ya no está: los candidatos que la tienda ha retirado (los de una categoría que
        #    hoy ha fallado se conservan), las propuestas de tandas anteriores que no se llegaron a
        #    valorar y la posibilidad de deshacer las decisiones de la tanda anterior.
        for ref, row in old.items():
            if ref not in fresh and (row.section in listed or row.section not in active):
                db.delete(row)
        stale = select(ShopItem).where(ShopItem.store == store, ShopItem.status == NEW, ShopItem.batch < today)
        for item in db.scalars(stale):
            _retire(item, EXPIRED)
            result["expired"] += 1
        _set(db, K_MORE, None)
        db.commit()
        _close_undo(db, store)

        # 3. El detalle y las fotos, solo de los mejores.
        context = Context.load(db)
        in_season = [row for row in fresh.values() if not out_of_season(row, today)]
        result["added"] = len(_promote(db, context, _ranked(context, in_season, limit * 2), limit, today, failed))

    # 4. Los «me gusta» de esta tienda: ¿siguen ahí y queda alguna talla?
    for item in db.scalars(select(ShopItem).where(ShopItem.store == store, ShopItem.status == LIKED)):
        try:
            detail = connector.detail(item.store_data)
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
            item.price_cents = detail.price_cents or item.price_cents
        db.commit()

    if result["ok"]:
        result["ok_day"] = today.isoformat()
    result["error"] = errors[0] if errors else None
    result["errors"] = errors[:20]
    _save_status(db, store, result)
    db.commit()
    log.info(
        "Compras: %s consultada (%s vistos, %s nuevos, %s caducados, %s peticiones fallidas)",
        store, result["found"], result["added"], result["expired"], result["failed"],
    )
    return result


def refresh(db: Session, today: date | None = None, limit: int | None = None, stores: list[str] | None = None) -> dict:
    """Una tanda: consulta las tiendas indicadas (por defecto, todas las activadas), una detrás de otra."""
    total = {"ok": False, "found": 0, "added": 0, "expired": expire_old(db), "failed": 0, "errors": []}
    for store in stores if stores is not None else enabled_stores(db):
        if store not in shops.CONNECTORS:
            continue
        try:
            result = refresh_store(db, store, today, limit)
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
    return total


def more(db: Session, store: str | None = None, category: str | None = None, limit: int | None = None,
         today: date | None = None) -> dict:
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
    ranked = _ranked(context, candidates_left(db, today, store, category), limit * 2)
    scores = _promote(db, context, ranked, limit, today, _failure_log(result))
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


# ---------- En segundo plano

_lock = threading.Lock()  # una sola tanda a la vez, sea la consulta semanal o un «Ver más»
_running = threading.Event()
_stop = threading.Event()
_worker: threading.Thread | None = None
_scheduler: threading.Thread | None = None
_job = "consulta"  # qué es lo que está en marcha: la «consulta» del catálogo o un ver «mas»
FIRST_CHECK_SECONDS, CHECK_EVERY_SECONDS = 30, 3600


def is_running() -> bool:
    return _running.is_set()


def running_job() -> str | None:
    """«consulta» o «mas» mientras hay una tanda en marcha; None si no hay ninguna."""
    return _job if _running.is_set() else None


def _run_locked(job) -> None:
    """Hace el trabajo (`job(db)`) con el cerrojo ya cogido y lo suelta al acabar, pase lo que pase."""
    try:
        with SessionLocal() as db:
            job(db)
    except Exception:
        log.exception("Compras: la tanda falló")
    finally:
        _running.clear()
        _lock.release()


def _start(job, kind: str) -> bool:
    global _worker, _job
    if not _lock.acquire(blocking=False):
        return False
    _job = kind
    _running.set()
    _worker = threading.Thread(target=_run_locked, args=(job,), name=f"armario-compras-{kind}", daemon=True)
    _worker.start()
    return True


def start_refresh(stores: list[str] | None = None) -> bool:
    """Lanza una tanda en un hilo aparte y vuelve ya. False si ya había una en marcha."""
    return _start(lambda db: refresh(db, stores=stores), "consulta")


def start_more(store: str | None = None, category: str | None = None) -> bool:
    """Lanza un «Ver más» en un hilo aparte y vuelve ya. False si ya había una tanda en marcha."""
    return _start(lambda db: more(db, store, category), "mas")


def wait_idle(timeout: float = 30) -> None:
    """Espera a que termine la tanda en marcha (para los tests)."""
    if _worker is not None:
        _worker.join(timeout)


def _loop() -> None:
    global _job
    delay = FIRST_CHECK_SECONDS
    while not _stop.wait(delay):
        delay = CHECK_EVERY_SECONDS
        try:
            with SessionLocal() as db:
                due = due_stores(db)
            if due and _lock.acquire(blocking=False):
                _job = "consulta"
                _running.set()
                _run_locked(lambda db: refresh(db, stores=due))
        except Exception:
            log.exception("Compras: fallo en el bucle de la tanda semanal")


def start_scheduler() -> None:
    """El bucle que arranca con la app: mira cada hora si a alguna tienda le toca consulta hoy."""
    global _scheduler
    if _scheduler is not None and _scheduler.is_alive():
        return
    _stop.clear()
    _scheduler = threading.Thread(target=_loop, name="armario-compras", daemon=True)
    _scheduler.start()


def stop_scheduler() -> None:
    _stop.set()
