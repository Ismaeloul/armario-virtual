"""Compras (Fase 4): trae novedades de las tiendas, las puntúa contra el armario y lleva su estado.

Aquí no hay IA. La nota de un producto sale de cuatro cosas, de la que más pesa a la que menos:

  1. Con cuántas prendas del armario combina (las reglas de estilo más lo aprendido en Gustos:
     la misma afinidad que usan Hoy y Gustos, pareja a pareja).
  2. Si tapa un hueco: un tipo de prenda que no hay, un color que falta en ese tipo, o una
     categoría con muy pocas prendas.
  3. Si repite lo que ya hay (mismo tipo y mismo color): resta.
  4. Lo que el usuario ha ido diciendo en la propia pestaña con «me gusta» / «no me gusta»:
     preferencias por tipo de prenda, color y franja de precio.

La IA solo entra cuando el usuario marca «La he comprado»: entonces se analizan las fotos guardadas
y la prenda pasa al armario. La app nunca compra ni guarda datos de pago: solo enlaza a la tienda.
"""
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import catalog, config
from ..db import SessionLocal
from ..models import Garment, Setting, ShopItem, now_utc
from . import ai, outfits, shops, storage
from .ai.base import build_prompt
from .shops import ShopError

log = logging.getLogger("armario.compras")

NEW, LIKED, DISCARDED, BOUGHT, EXPIRED = "nuevo", "gustado", "descartado", "comprado", "caducado"

LIKED_DAYS = 30  # lo que dura un «me gusta» antes de caducar
EXPIRES_SOON_DAYS = 5  # desde cuándo se avisa de que caduca pronto

# --- Pesos de la nota (de 0 a 100)
GOOD_PAIR = 60  # afinidad de la pareja producto + prenda desde la que se cuenta que «combina»
W_MATCH = 40.0  # por la fracción de prendas complementarias del armario con las que combina
GAP_TYPE = 20.0  # el armario no tiene ninguna prenda de ese tipo
GAP_COLOR = 10.0  # tiene el tipo, pero no en ese color
GAP_CATEGORY = 10.0  # la categoría entera tiene muy pocas prendas…
FEW_IN_CATEGORY = 3  # …menos de estas
DUPLICATE = -12.0  # por cada prenda del mismo tipo y color que ya hay (hasta MAX_DUPLICATES)
MAX_DUPLICATES = 3
# Lo aprendido en la propia pestaña, con la opinión entre -1 y 1.
W_PREF_TYPE, W_PREF_COLOR, W_PREF_PRICE = 15.0, 10.0, 8.0
PREF_PRIOR_VOTES = 2.0  # votos neutros de relleno: una sola opinión no decide
CLEAR_PREF = 0.35  # opinión a partir de la cual se enseña como motivo

# Franjas de precio, en céntimos: hasta 25 €, hasta 50 €, hasta 80 € y más.
PRICE_BANDS = ((2500, "hasta_25"), (5000, "hasta_50"), (8000, "hasta_80"))

# --- Claves de la tabla settings
K_STORES, K_CATEGORIES = "shop_stores", "shop_categories"
K_STATUS = "shop_status"  # tienda -> cómo fue su última consulta (ver `store_status`)


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


def price_band(cents: int) -> str:
    return next((name for limit, name in PRICE_BANDS if cents < limit), "mas_de_80")


@dataclass
class ShopTaste:
    """Me gusta / no me gusta de la tienda, por tipo, color y franja de precio: clave -> [neto, total]."""

    types: dict[str, list[float]] = field(default_factory=dict)
    colors: dict[str, list[float]] = field(default_factory=dict)
    prices: dict[str, list[float]] = field(default_factory=dict)

    def learn(self, item, liked: bool) -> None:
        for table, key in ((self.types, item.type), (self.colors, item.color), (self.prices, price_band(item.price_cents))):
            entry = table.setdefault(key, [0.0, 0.0])
            entry[0] += 1.0 if liked else -1.0
            entry[1] += 1.0

    @staticmethod
    def opinion(table: dict, key: str) -> float:
        """De -1 a 1, suavizada: con pocos votos se queda cerca de 0."""
        net, total = table.get(key, (0.0, 0.0))
        return net / (total + PREF_PRIOR_VOTES)


def load_shop_taste(db: Session) -> ShopTaste:
    """Cuenta como «me gusta» todo lo que alguna vez gustó (aunque luego se quitara o se comprara) y
    como «no me gusta» lo descartado sin haberlo guardado. Lo caducado sin valorar no dice nada."""
    learned = ShopTaste()
    for item in db.scalars(select(ShopItem).where(ShopItem.status.in_((LIKED, DISCARDED, BOUGHT)))):
        if item.liked_at is not None:
            learned.learn(item, True)
        elif item.status == DISCARDED:
            learned.learn(item, False)
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
# categoría -> (una, varias) para «Solo tienes 2 …»
_CATEGORY_FORMS = {
    "parte_superior": ("parte de arriba", "partes de arriba"),
    "capa_exterior": ("chaqueta o abrigo", "chaquetas y abrigos"),
    "parte_inferior": ("pantalón", "pantalones"),
    "calzado": ("par de zapatos", "pares de zapatos"),
}


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


def out_of_season(product, today: date) -> bool:
    """Fuera de mayo-septiembre no se propone ropa de verano (la misma regla que el outfit de Hoy)."""
    return not outfits.warm_months(today) and outfits.summer_only(candidate_item(product))


def score(product, wardrobe: list[outfits.Item], taste=None, prefs: ShopTaste | None = None) -> tuple[float, list[dict]]:
    """La nota de un producto contra el armario (0-100) y los motivos, legibles, a favor y en contra."""
    candidate = candidate_item(product)
    reasons: list[dict] = []
    total = 0.0

    def reason(text: str, kind: str = "pro") -> None:
        reasons.append({"text": text, "kind": kind})

    # 1. Con cuántas prendas combina: las de las otras categorías, sin mezclar verano con invierno.
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

    # 2. Huecos del armario y 3. duplicados.
    same_type = [g for g in wardrobe if g.type == candidate.type]
    same = sum(1 for g in same_type if g.color == candidate.color)
    in_category = sum(1 for g in wardrobe if g.category == candidate.category)
    if not same_type:
        total += GAP_TYPE
        reason(_none(candidate.type))
    elif not same:
        total += GAP_COLOR
        reason(_none(candidate.type, candidate.color))
    else:
        total += DUPLICATE * min(same, MAX_DUPLICATES)
        reason(f"Ya tienes {_typed(candidate.type, same, candidate.color)}", "contra")
    if in_category < FEW_IN_CATEGORY:
        total += GAP_CATEGORY
        if in_category:
            one, many = _CATEGORY_FORMS[candidate.category]
            reason(f"Solo tienes {in_category} {one if in_category == 1 else many}")

    # 4. Lo que el usuario ha ido diciendo en la tienda.
    if prefs is not None:
        plural, feminine = _TYPE_FORMS[candidate.type]
        article = "las" if feminine else "los"
        by_type = prefs.opinion(prefs.types, candidate.type)
        by_color = prefs.opinion(prefs.colors, candidate.color)
        by_price = prefs.opinion(prefs.prices, price_band(product.price_cents))
        total += W_PREF_TYPE * by_type + W_PREF_COLOR * by_color + W_PREF_PRICE * by_price
        if by_type >= CLEAR_PREF:
            reason(f"Te suelen gustar {article} {plural}")
        elif by_type <= -CLEAR_PREF:
            reason(f"Sueles descartar {article} {plural}", "contra")
        if by_color >= CLEAR_PREF:
            reason(f"Te suele gustar el {candidate.color}")
        elif by_color <= -CLEAR_PREF:
            reason(f"Sueles descartar el {candidate.color}", "contra")
        if by_price >= CLEAR_PREF:
            reason("Precio como los que te gustan")
        elif by_price <= -CLEAR_PREF:
            reason("Sueles descartar este rango de precio", "contra")

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


def _retire(item: ShopItem, status: str) -> None:
    """Deja de enseñarse: se queda la fila (para no volver a proponerlo) y se borran sus fotos."""
    for photo_id in item.photos or []:
        storage.delete(photo_id)
    item.photos = []
    item.status = status


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
    item.liked_at = now
    item.expires_at = now + timedelta(days=LIKED_DAYS)
    db.commit()
    rescore_pending(db)


def dislike(db: Session, item: ShopItem) -> None:
    _retire(item, DISCARDED)
    db.commit()
    rescore_pending(db)


def remove_liked(db: Session, item: ShopItem) -> None:
    _retire(item, DISCARDED)
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
    item.ai_draft = saved_draft
    item.photos = []  # las fotos pasan a ser de la prenda: una foto, un solo dueño
    db.commit()
    rescore_pending(db)  # el armario ha cambiado: lo que era un hueco ya no lo es
    return garment, draft is not None


# ---------- La tanda


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
    """Reparte entre categorías: la mejor de cada una, luego la segunda de cada una…"""
    queues = sorted((q for q in queues if q), key=lambda q: -q[0][0])
    for position in range(max((len(q) for q in queues), default=0)):
        for queue in queues:
            if position < len(queue):
                yield queue[position]


def refresh_store(db: Session, store: str, today: date | None = None, limit: int | None = None) -> dict:
    """Consulta UNA tienda: trae sus novedades, deja las mejores como propuestas y revisa sus «me gusta».

    Nunca lanza por culpa de la tienda: lo que falla se apunta, se guarda en el estado de la tienda
    (`store_status`) y se sigue con lo demás.
    """
    now = now_utc()
    today = today or outfits.local_today()
    limit = config.SHOP_BATCH_SIZE if limit is None else limit
    connector = shops.CONNECTORS[store]
    previous = store_status(db, store) or {}
    result = {
        "at": now.isoformat(), "day": today.isoformat(), "ok": False, "ok_day": previous.get("ok_day"),
        "found": 0, "added": 0, "expired": 0, "failed": 0, "error": None, "errors": [],
    }
    errors: list[str] = result["errors"]

    def failed(what: str, exc: Exception) -> None:
        message = str(exc) if isinstance(exc, ShopError) else "error inesperado en el conector"
        result["failed"] += 1
        errors.append(f"{what}: {message}")

    # Se apunta ya el intento: si el proceso muere a medias, hoy no se vuelve a insistir.
    _save_status(db, store, {**previous, "day": today.isoformat()})
    db.commit()

    context = Context.load(db)
    seen = set(db.scalars(select(ShopItem.product_ref)))  # lo visto alguna vez, sea cual sea su estado

    # 1. Listados: una petición por categoría. Solo datos del listado, sin fotos ni detalle.
    queues: list[list[tuple]] = []
    for slug in active_categories(db, store):
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
        queue = []
        for product in products:
            if product.product_ref in seen:
                continue
            seen.add(product.product_ref)  # la misma prenda puede salir en dos categorías
            if out_of_season(product, today):
                continue
            value, reasons = context.score(product)
            queue.append((value, reasons, product))
        queue.sort(key=lambda entry: -entry[0])
        queues.append(queue)

    if result["ok"]:
        # 2. Las propuestas de tandas anteriores que no se llegaron a valorar caducan.
        stale = select(ShopItem).where(ShopItem.store == store, ShopItem.status == NEW, ShopItem.batch < today)
        for item in db.scalars(stale):
            _retire(item, EXPIRED)
            result["expired"] += 1
        db.commit()

        # 3. El detalle y las fotos, solo de las mejores. Si una no sirve, entra la siguiente
        #    (con un tope de peticiones, por educación con la tienda).
        attempts = 0
        for value, reasons, product in _round_robin(queues):
            if result["added"] >= limit or attempts >= limit * 2:
                break
            attempts += 1
            try:
                detail = connector.detail(product.store_data)
                if detail is None or not detail.photo_urls or not detail.in_stock:
                    continue  # ya no existe, no tiene foto de producto o no queda ninguna talla
                photos = _save_photos(connector, detail.photo_urls)
            except Exception as exc:
                if not isinstance(exc, ShopError):
                    log.exception("Compras: error inesperado con %s", product.product_ref)
                failed(product.name, exc)
                continue
            db.add(
                ShopItem(
                    store=product.store, product_ref=product.product_ref, name=product.name[:160],
                    price_cents=detail.price_cents or product.price_cents, url=product.url,
                    store_color=product.store_color[:60], store_color_hex=detail.color_hex,
                    section=product.section, store_data=product.store_data, type=product.type,
                    category=product.category, color=product.color, pattern=product.pattern,
                    style=product.style, season=product.season,
                    details=f"{product.details} {detail.description}".strip(),
                    photos=photos, score=value, reasons=reasons, status=NEW, batch=today,
                    first_seen_at=now, last_checked_at=now_utc(), in_stock=True, sizes=detail.sizes,
                )
            )
            db.commit()
            result["added"] += 1

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


# ---------- En segundo plano

_lock = threading.Lock()  # una sola tanda a la vez
_running = threading.Event()
_stop = threading.Event()
_worker: threading.Thread | None = None
_scheduler: threading.Thread | None = None
FIRST_CHECK_SECONDS, CHECK_EVERY_SECONDS = 30, 3600


def is_running() -> bool:
    return _running.is_set()


def _run_locked(stores: list[str] | None = None) -> None:
    """Hace la tanda con el cerrojo ya cogido y lo suelta al acabar, pase lo que pase."""
    try:
        with SessionLocal() as db:
            refresh(db, stores=stores)
    except Exception:
        log.exception("Compras: la tanda falló")
    finally:
        _running.clear()
        _lock.release()


def start_refresh(stores: list[str] | None = None) -> bool:
    """Lanza una tanda en un hilo aparte y vuelve ya. False si ya había una en marcha."""
    global _worker
    if not _lock.acquire(blocking=False):
        return False
    _running.set()
    _worker = threading.Thread(target=_run_locked, args=(stores,), name="armario-compras-tanda", daemon=True)
    _worker.start()
    return True


def wait_idle(timeout: float = 30) -> None:
    """Espera a que termine la tanda en marcha (para los tests)."""
    if _worker is not None:
        _worker.join(timeout)


def _loop() -> None:
    delay = FIRST_CHECK_SECONDS
    while not _stop.wait(delay):
        delay = CHECK_EVERY_SECONDS
        try:
            with SessionLocal() as db:
                due = due_stores(db)
            if due and _lock.acquire(blocking=False):
                _running.set()
                _run_locked(due)
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
