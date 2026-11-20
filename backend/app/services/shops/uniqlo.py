"""Conector de Uniqlo (Francia, hombre) a través de API.SH, un servicio de pago (ver services/apish.py).

Por qué: Uniqlo da «Access Denied» (Akamai) a un programa y también a nuestro Chromium. El usuario decidió el
19-11-2026 leerla con API.SH, que ha contratado él. Es la ÚNICA tienda que va así; las demás no cambian.

Lo que se pide (documentación en https://api.sh/docs/uniqlo-search y /docs/uniqlo-product):

- `GET /uniqlo/v1/search?country=fr&q=<palabra>&category=37609&limit=100&sort=newest&page=N`, 1 crédito por
  página. Comprobado con llamadas reales el 19-11-2026: `category` SOLO filtra con el id de GÉNERO (37609 =
  hombre); con los ids de clase de los facets (84995 «T-shirts, Sweats & Polaires», 100162, 100160, 84994,
  84996) devuelve 0 productos, con `q` y sin él, y sin `q` tampoco sale nada. Así que no se pueden pedir
  todas las secciones juntas en una sola serie de páginas: cada sección es una palabra de búsqueda (`q`)
  con el filtro de hombre, y el tipo de cada producto sale de su nombre (la búsqueda es aproximada: «t-shirt»
  trae también camisas y bolsos; lo que no se reconoce por el nombre, fuera).
- Solo productos `gender_category` MEN o UNISEX (el filtro ya deja solo esos, pero se mira igual).
- Precio: `promo_price` si lo hay (rebajado: el de antes es `regular_price`) o `price`.
- Fotos: de `images_by_color`, una por color. Uniqlo tiene dos clases: las `WesternCommon/…/goods_…` son de
  producto SIN modelo y las `eu/…/eugoods_…`, CON modelo (comprobado en el listado de su web, que lo decía en
  `images.main[color].model`). API.SH no dice si hay modelo, así que solo se usan las primeras: un color sin
  foto de producto no se propone (en la página real de «t-shirt», 49 de 292 colores). Las `extra_images` de
  la ficha no se usan: no se sabe cuáles llevan modelo.
- Sin tallas en el listado («Tallas: míralas en la tienda»). La ficha (`detail`) sale de lo guardado del
  listado (`listing.detail_from`), sin gastar otra llamada.

Ahorro de créditos (pedido por el usuario): `limit=100` siempre y `sort=newest`. En la consulta semanal se deja
de pasar páginas en cuanto una página entera son productos ya vistos en otra consulta (`apish_uniqlo_seen`):
una semana normal cuesta una página por sección activa. Una vez al mes (o si no hay nada de Uniqlo guardado)
se recorre entero, hasta `next_page = null` o el tope de páginas (`ARMARIO_SHOP_MAX_PAGES_UNIQLO`, 5), para
retirar lo que ya no está. Si se paró antes, la sección no retira nada (`listed_all`).

Gasto estimado (13 secciones; «t-shirt» de hombre tenía 265 productos = 3 páginas): primera consulta, unas
20-25 llamadas (como mucho 65 con el tope de 5 por sección); una semana normal, 13 (una por sección activa;
menos si se desactivan secciones); al mes, unas 13 x 3 + 22 = ~60-80, muy por debajo del tope de 300.

El buscador: un enlace de uniqlo.com -> `/uniqlo/v1/product` (1 crédito, la única llamada a la ficha); texto
libre -> `/search` con `q` y el filtro de hombre (1 crédito), y solo si Uniqlo está activada en Tiendas (el
buscador pregunta a todas las tiendas, y no se gasta un crédito por cada búsqueda de una tienda que el usuario
no usa). Los dos cuentan para el mismo tope.
"""
import dataclasses
import math
import re
import threading
import time
from datetime import date, timedelta
from urllib.parse import parse_qs, urlsplit

from .. import apish
from . import crawl
from .base import NotThisStore, SearchError, ShopError
from .listing import _LINK, Entry, ListingConnector, euros, fix_text, make_product

BASE = "https://www.uniqlo.com"
MEN = 37609  # el género «hombre» en su taxonomía (facets.categories.genders)
PAGE_SIZE = 100
SEARCH_SIZE = 24  # el buscador de texto: una página (1 crédito)
_GENDERS = {"MEN", "UNISEX"}
K_SEEN = "apish_uniqlo_seen"  # id de producto -> último día en que salió (para parar de paginar)
K_FULL = "apish_uniqlo_full"  # sección -> mes del último recorrido completo («2026-11»)
SEEN_DAYS = 120  # lo visto hace más se olvida (el ajuste no crece sin fin)
# Stock: la búsqueda no dice qué tallas quedan; la ficha (`/product`, 1 crédito) sí, y sirve para todos los
# colores del producto. Se pide antes de enseñar una prenda (las finalistas de cada tanda, los «me gusta» de la
# semana, el cambio de color) y se guarda unas horas. Si quedan pocos créditos del tope, se deja de mirar y se
# fía del listado, para que no falte para las consultas semanales.
STOCK_TTL = 12 * 3600
STOCK_RESERVE = 40
_stock: dict[str, tuple[float, dict | None]] = {}
_stock_lock = threading.Lock()
_PRODUCT_ID = re.compile(r"\b(E?\d{6}-\d{3})\b", re.IGNORECASE)

# slug -> (nombre para el usuario, palabra de búsqueda, tipo de la sección). Los slugs son los de antes, para
# que lo elegido en Tiendas se conserve.
SECTIONS = {
    "t-shirts": ("Camisetas", "t-shirt", "camiseta"),
    "sweats": ("Sudaderas", "sweat", "sudadera"),
    "chemises": ("Camisas", "chemise", "camisa"),
    "polos": ("Polos", "polo", "polo"),
    "pulls": ("Jerséis", "pull", "jersey"),
    "cardigans": ("Cárdigans", "cardigan", "jersey"),
    "blousons": ("Chaquetas", "veste", "chaqueta"),
    "manteaux": ("Abrigos", "manteau", "abrigo"),
    "doudounes": ("Plumíferos", "doudoune", "abrigo"),
    "jeans": ("Vaqueros", "jean", "vaquero"),
    "chinos": ("Chinos", "chino", "chino"),
    "pantalons": ("Pantalones", "pantalon", "pantalón"),
    "shorts": ("Bermudas", "short", "pantalón corto"),
}


def product_photo(url) -> str | None:
    """La foto si es de producto sin modelo (`WesternCommon/…/goods_…`); None si es con modelo o no hay."""
    text = str(url or "").split("?")[0]
    return text if "/WesternCommon/" in text and "/goods_" in text else None


def _link(product_id: str, group: str, code: str) -> str:
    return f"{BASE}/fr/fr/products/{product_id}/{group}?colorDisplayCode={code}"


def _sizes(product: dict) -> dict[str, list[list]] | None:
    """Las tallas de cada color con si queda, de los `skus` de la ficha. None si la ficha no los trae."""
    skus = [s for s in product.get("skus") or [] if isinstance(s, dict)]
    if not skus:
        return None
    order = [str(s.get("name")) for s in product.get("sizes") or [] if isinstance(s, dict)]
    found: dict[str, dict[str, bool]] = {}
    for sku in skus:
        code, size = str(sku.get("color_code") or ""), str(sku.get("size") or "")
        if code and size:
            left = str(sku.get("stock_status") or "").upper() not in ("STOCK_OUT", "OUT_OF_STOCK")
            found.setdefault(code, {})[size] = found.get(code, {}).get(size, False) or left
    rank = {name: i for i, name in enumerate(order)}
    return {code: sorted(([n, s] for n, s in sizes.items()), key=lambda p: rank.get(p[0], 99))
            for code, sizes in found.items()}


def entries(item: dict, sizes: dict[str, list[list]] | None = None) -> list[Entry]:
    """Los colores con foto de producto sin modelo de un producto de API.SH, cada uno como un producto. Vale
    para la búsqueda y para la ficha (`/product`, que además trae tallas con stock y composición)."""
    item = item if isinstance(item, dict) else {}
    product_id, group = str(item.get("id") or ""), str(item.get("price_group") or "00")
    if not product_id or str(item.get("gender_category") or "").upper() not in _GENDERS:
        return []
    if item.get("store_stock_only") is True:
        return []  # solo se vende en tienda física: no se puede pedir por internet
    promo = item.get("promo_price")
    price = euros(promo) or euros(item.get("price")) or euros(item.get("regular_price"))
    images = item.get("images_by_color") or {}
    flat = []
    for color in item.get("colors") or []:
        code = str((color or {}).get("code") or "")
        if code and product_photo(images.get(code)):
            flat.append(color)
    ref = str(item.get("l1_id") or "") or product_id.lstrip("Ee").split("-")[0]
    colors = [{"id": f"{product_id}-{group}-{c['code']}", "name": fix_text(c.get("name")).capitalize(),
               "url": _link(product_id, group, c["code"])} for c in flat]
    description = str(item.get("design_detail") or item.get("description") or "").replace("- ", " ")
    found = []
    for color in flat:
        code = color["code"]
        own_sizes = sizes.get(code) if sizes is not None else None
        found.append(Entry(
            id=f"{product_id}-{group}-{code}",
            name=fix_text(item.get("name")),
            price_cents=price,
            # Rebajado: hay `promo_price` y es menor que `regular_price` (lo comprueba `old_price`).
            old_price_cents=euros(item.get("regular_price")) if promo is not None else None,
            old_price_known=True,
            url=_link(product_id, group, code),
            color=fix_text(color.get("name")).capitalize(),
            photos=[product_photo(images[code])],
            sizes=own_sizes,
            composition=str(item.get("composition") or ""),
            description=description,
            colors=colors,
            ref=ref,
            # La familia de color, en inglés («BLACK»), por si el nombre no dice nada conocido.
            color_hint=str(color.get("filter") or color.get("group") or ""),
            sold_out=own_sizes is not None and bool(own_sizes) and not any(left for _n, left in own_sizes),
        ))
    return found


def parse_search(data: dict, section: str | None) -> tuple[list, list[str], int | None, int | None]:
    """(productos, ids de todos los productos de la página, página siguiente o None, total) de una búsqueda."""
    data = data if isinstance(data, dict) else {}
    items = [p for p in data.get("products") or [] if isinstance(p, dict)]
    products, refs = [], set()
    for item in items:
        for found in entries(item):
            # Sin tipo por defecto: la búsqueda es aproximada y lo que no se reconoce por el nombre (bolsos,
            # gorros…) no se mete en la sección.
            product = make_product("uniqlo", "Uniqlo", found, section or "", None)
            if product is None or product.product_ref in refs:
                continue
            refs.add(product.product_ref)
            products.append(product)
    ids = [str(p.get("id")) for p in items if p.get("id")]
    following = data.get("next_page")
    total = data.get("total")
    return (products, ids, following if isinstance(following, int) else None,
            total if isinstance(total, int) else None)


# ---------- Lo visto y los recorridos completos (para no gastar créditos de más)


def seen_ids() -> dict[str, str]:
    stored = apish.read_setting(K_SEEN, {}) or {}
    return stored if isinstance(stored, dict) else {}


def note_seen(ids: list[str], today: date | None = None) -> None:
    if not ids:
        return
    today = today or date.today()
    oldest = (today - timedelta(days=SEEN_DAYS)).isoformat()
    stored = {k: v for k, v in seen_ids().items() if isinstance(v, str) and v >= oldest}
    stored.update({pid: today.isoformat() for pid in ids})
    apish.write_setting(K_SEEN, stored)


def full_month(slug: str) -> str | None:
    stored = apish.read_setting(K_FULL, {}) or {}
    return stored.get(slug) if isinstance(stored, dict) else None


def mark_full(slug: str) -> None:
    stored = apish.read_setting(K_FULL, {}) or {}
    stored = stored if isinstance(stored, dict) else {}
    apish.write_setting(K_FULL, {**stored, slug: apish.month_now()})


def _nothing_stored() -> bool:
    from sqlalchemy import func, select

    from ...models import ShopItem

    with apish._session() as db:
        return not db.scalar(select(func.count()).select_from(ShopItem).where(ShopItem.store == "uniqlo"))


def _store_enabled() -> bool:
    stores = apish.read_setting("shop_stores", []) or []  # = shopping.K_STORES
    return "uniqlo" in stores


class UniqloConnector(ListingConnector):
    key = "uniqlo"
    name = "Uniqlo"
    domain = "uniqlo.com"
    needs_browser = False
    heavy = False  # unas pocas llamadas a un servicio: nada de navegador
    # Va por API.SH (services/apish.py): la clave se pega en Ajustes y el tope de créditos del mes es común a
    # todas las tiendas que lo usen. El panel Tiendas solo dice si falta la clave o si se ha llegado al tope.
    uses_apish = True
    # No se sabe qué día saca novedades: los lunes (ver el reparto en shops/__init__.py).
    refresh_weekday = 0  # lunes = 0
    categories = {slug: label for slug, (label, _q, _type) in SECTIONS.items()}
    section_types = {slug: kind for slug, (_label, _q, kind) in SECTIONS.items()}

    def __init__(self):
        super().__init__()
        self._listed_all: dict[str, bool] = {}

    def unavailable(self) -> str | None:
        """Sin clave o con el tope de créditos del mes, no se consulta (y no se llama a nada)."""
        return apish.missing()

    def listed_all(self, slug: str) -> bool:
        """¿La última lectura de la sección llegó al final? Si paró antes (ya vistos o el tope de páginas),
        lo guardado que no ha salido NO se retira (ver shopping.refresh_store)."""
        return self._listed_all.get(slug, True)

    def _params(self, q: str, page: int, limit: int = PAGE_SIZE) -> dict:
        return {"q": q, "country": "fr", "category": str(MEN), "limit": limit, "sort": "newest", "page": page}

    def list_category(self, slug: str) -> list:
        """La sección por páginas de 100, de lo más nuevo a lo más viejo. Semana normal: hasta una página en
        la que todo ya se había visto. Una vez al mes (o sin nada guardado): entera. Si falla a mitad,
        `crawl.Partial` con lo leído."""
        _label, q, _type = SECTIONS[slug]
        full = full_month(slug) != apish.month_now() or _nothing_stored()
        seen = set(seen_ids())
        limit = max(1, crawl.max_pages(self.key))
        found: dict[str, object] = {}
        self._listed_all[slug] = False
        reached_end = False
        page = 1
        try:
            while page <= limit:
                crawl.before_page()
                data = apish.get("/uniqlo/v1/search", self._params(q, page))
                products, ids, following, total = parse_search(data or {}, slug)
                crawl.page_read(len(products))
                if page == 1 and total:
                    crawl.section_total(min(limit, math.ceil(total / PAGE_SIZE)) if full else 1)
                for product in products:
                    found.setdefault(product.product_ref, product)
                note_seen(ids)
                if following is None or not ids:
                    reached_end = True
                    break
                if not full and all(pid in seen for pid in ids):
                    break  # una página entera ya vista: lo de detrás también (van por novedad)
                page = following
        except ShopError as exc:
            if not found:
                raise
            raise crawl.Partial(list(found.values()), exc) from exc
        self._listed_all[slug] = reached_end
        if full and reached_end:
            mark_full(slug)
        return list(found.values())

    def search(self, query: str, limit: int = 12) -> list:
        """Un enlace de uniqlo.com -> su ficha (1 crédito). Texto libre -> una búsqueda de hombre (1 crédito),
        solo si Uniqlo está activada. Sin clave o con el tope, un enlace se explica y el texto se ignora."""
        text = " ".join((query or "").split())
        link = _LINK.search(text)
        if link:
            url = link.group().rstrip(".,;)")
            host = (urlsplit(url if "://" in url else f"https://{url}").hostname or "").lower()
            if host != self.domain and not host.endswith("." + self.domain):
                raise NotThisStore("Todavía no sé buscar en esa tienda")
            return self._search_link(url, limit)
        if not text or apish.missing() or not _store_enabled():
            raise NotThisStore("Todavía no sé buscar en esa tienda")
        try:
            data = apish.get("/uniqlo/v1/search", self._params(text, 1, SEARCH_SIZE))
        except ShopError:
            raise NotThisStore("Uniqlo no responde ahora") from None  # el texto libre no es solo de Uniqlo
        products, _ids, _next, _total = parse_search(data or {}, None)
        return products[:limit]

    def _search_link(self, url: str, limit: int) -> list:
        why = apish.missing()
        if why:
            raise SearchError(f"Uniqlo: {why[:1].lower()}{why[1:]}")
        match = _PRODUCT_ID.search(urlsplit(url if "://" in url else f"https://{url}").path)
        if not match:
            raise SearchError("Ese enlace de Uniqlo no es de un producto")
        product_id = match.group(1).upper()
        product_id = product_id if product_id.startswith("E") else f"E{product_id}"
        data = apish.get("/uniqlo/v1/product", {"id": product_id, "country": "fr"})
        if not data:
            raise SearchError("Esa prenda ya no está en Uniqlo")
        if str(data.get("gender_category") or "").upper() not in _GENDERS:
            raise SearchError("Esa prenda de Uniqlo no es de hombre")
        wanted = (parse_qs(urlsplit(url).query).get("colorDisplayCode") or [""])[0]
        products = []
        for found in entries(data, _sizes(data)):
            product = make_product("uniqlo", "Uniqlo", found, "", None)
            if product is not None:
                products.append(product)
        if not products:
            raise SearchError("Uniqlo solo tiene fotos con modelo de esa prenda: no la puedo guardar")
        products.sort(key=lambda p: not p.product_ref.endswith(f"-{wanted}"))  # el color del enlace, primero
        return products[:limit]

    def _product(self, product_id: str):
        """La ficha de API.SH de un producto (guardada unas horas). None si ya no existe; `...` si no se
        sabe (sin clave, pocos créditos o el servicio falla): entonces vale lo del listado."""
        now = time.time()
        with _stock_lock:
            cached = _stock.get(product_id)
            if cached is not None and now - cached[0] < STOCK_TTL:
                return cached[1]
        used, limit = apish.credits()
        if apish.missing() or used >= limit - STOCK_RESERVE:
            return ...
        try:
            data = apish.get("/uniqlo/v1/product", {"id": product_id, "country": "fr"})
        except ShopError:
            return ...
        with _stock_lock:
            _stock[product_id] = (now, data)
        return data

    def cached_detail(self, store_data: dict):
        """La del listado, con las tallas que quedan según la ficha de Uniqlo. None si ese color ya no se
        vende (o el producto ya no está)."""
        from .listing import detail_from

        base = detail_from(self.key, store_data)
        own = str(store_data.get("id") or "")
        if base is None or own.count("-") < 3:
            return base
        data = self._product(own.rsplit("-", 2)[0])
        if data is ...:
            return base
        if not data:
            return None
        found = next((e for e in entries(data, _sizes(data)) if e.id == own), None)
        if found is None:
            return None  # ese color ya no está (o solo en tienda física)
        if not found.sizes:
            return base
        return dataclasses.replace(
            base,
            sizes=[{"name": str(n), "in_stock": bool(left)} for n, left in found.sizes],
            stock_known=True,
            sold_out=found.sold_out,
            composition=base.composition or " ".join(str(found.composition).split()),
        )

    def detail(self, store_data: dict):
        """La del listado con el stock de la ficha (ver `cached_detail`)."""
        if not isinstance((store_data or {}).get("snap"), dict):
            raise ShopError("sin datos guardados de ese color (sale en la próxima consulta semanal)")
        return self.cached_detail(store_data)
