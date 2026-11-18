"""Base común de las tiendas que solo se leen por su LISTADO, con navegador: Uniqlo, Mango, H&M, COS y Weekday
(Francia, hombre; investigado el 18-11-2026).

Lo acordado para estas cinco: se abren sus páginas con el navegador de serie (browser.py), como un usuario,
y se ESCUCHAN las respuestas JSON que pide la propia página (o se lee el JSON que la página ya trae dentro).
No se llama por nuestra cuenta a sus APIs internas imitando cabeceras ni identificadores de su web.

La ficha de producto NO se abre nunca: en H&M, COS y Weekday da «Access Denied» también con navegador, y en
las cinco el listado ya trae lo que hace falta (nombre, precio, color, fotos sin modelo y los otros colores; en
algunas, tallas con stock y composición). Así que cada producto del listado guarda una instantánea (`snap`) y
la ficha sale siempre de ahí (`cached_detail`), sin volver a la tienda: lo nuevo de la semana, «Ver más», la
reserva y el cambio de color (solo entre los colores ya preparados: `prepared_colors`). Las fotos salen de la
CDN de cada tienda, que responde a un cliente normal.

Sin tallas en el listado (Uniqlo, Mango, H&M, COS): `sizes` es None en la instantánea y la ficha sale con
`stock_known=False`. La interfaz dice «Tallas: míralas en la tienda» y al comprar se elige «Sin talla» o se
escribe a mano. Sin dato de stock, un «me gusta» no caduca por stock (solo por los 30 días).
"""
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from ... import catalog, config
from . import browser, crawl
from .base import NeedsBrowser, NotThisStore, SearchError, ShopDetail, ShopError, ShopProduct
from .estimate import brand_name, estimate_color, estimate_pattern, estimate_season, estimate_style, estimate_type
from .estimate import sentence_case
from .fetch import IMAGE, Fetcher

MAX_PHOTOS = 3
DESCRIPTION_MAX = 400
COMPOSITION_MAX = 300
MAX_COLORS = 16
_LINK = re.compile(r"(?:https?://|www\.)\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}/\S*", re.IGNORECASE)
_HEX = re.compile(r"#?([0-9a-fA-F]{6})")


def fix_text(text) -> str:
    """Espacios en orden y, si viene mal codificado («intÃ©rieur», visto en los textos de H&M), arreglado."""
    text = " ".join(str(text or "").split())
    if "Ã" in text or "â€" in text:
        try:
            text = text.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return text


def hex_color(value) -> str | None:
    """«4B5C7A», «#4b5c7a» o «51,56,64» -> «#4b5c7a». None si no tiene forma de tono."""
    text = str(value or "").strip()
    rgb = re.fullmatch(r"(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})", text)
    if rgb:
        parts = [int(n) for n in rgb.groups()]
        return "#" + "".join(f"{min(255, n):02x}" for n in parts)
    match = _HEX.fullmatch(text)
    return f"#{match.group(1).lower()}" if match else None


def euros(value) -> int | None:
    """34.99 -> 3499 céntimos. None si no es un precio."""
    try:
        cents = round(float(value) * 100)
    except (TypeError, ValueError):
        return None
    return cents if cents > 0 else None


@dataclass
class Entry:
    """Un producto en un color, tal como lo dice el listado de la tienda, antes de normalizarlo."""

    id: str  # único por producto + color dentro de la tienda (va en `product_ref`)
    name: str
    price_cents: int | None
    url: str
    color: str = ""  # el nombre del color como lo dice la tienda
    hex: str | None = None
    photos: list[str] = field(default_factory=list)  # solo de producto, sin modelo, ya con su tamaño
    sizes: list[list] | None = None  # [[nombre, queda]]; None = el listado no dice tallas
    composition: str = ""
    description: str = ""
    colors: list[dict] = field(default_factory=list)  # todos sus colores, este incluido: {"id","name","hex","url"}
    brand: str = ""
    ref: str = ""  # la referencia como la ve el cliente
    hint: str = ""  # la categoría de la tienda, para el tipo si el nombre no lo dice
    color_hint: str = ""  # otra forma de decir el color («BLACK»), por si el nombre no dice nada conocido
    sold_out: bool = False


def snapshot(entry: Entry, now: float | None = None) -> dict:
    """Lo que hace falta para la ficha sin volver a la tienda."""
    return {
        "at": int(now if now is not None else time.time()),
        "photos": entry.photos[:MAX_PHOTOS],
        "sizes": [[str(n), bool(s)] for n, s in entry.sizes] if entry.sizes is not None else None,
        "comp": fix_text(entry.composition)[:COMPOSITION_MAX],
        "desc": fix_text(entry.description)[:DESCRIPTION_MAX],
        "hex": entry.hex,
        "colors": [
            {"id": str(c["id"]), "name": fix_text(c.get("name")), "hex": hex_color(c.get("hex")), "url": c.get("url") or ""}
            for c in entry.colors[:MAX_COLORS] if c.get("id")
        ],
        "sold_out": bool(entry.sold_out),
    }


def make_product(store: str, store_name: str, entry: Entry, section: str, default_type: str | None,
                 now: float | None = None) -> ShopProduct | None:
    """De lo leído del listado a un producto normalizado. None si no cabe en el armario, si no tiene precio o
    si no hay ninguna foto de producto sin modelo (no se enseñan fotos con modelo)."""
    name = fix_text(entry.name)
    if not name or not entry.id or not entry.photos or entry.price_cents is None:
        return None
    name = name if any(ch.islower() for ch in name) else sentence_case(name)
    garment_type = estimate_type(name, default_type or estimate_type(entry.hint.replace("_", " ").replace("/", " ")))
    if garment_type is None:
        return None
    color = fix_text(entry.color)
    color = color if any(ch.islower() for ch in color) else color.capitalize()
    brand = brand_name(entry.brand) if entry.brand and entry.brand.strip().lower() != store_name.lower() else ""
    return ShopProduct(
        store=store,
        product_ref=f"{store}:{entry.id}",
        name=name,
        price_cents=entry.price_cents,
        url=entry.url,
        store_color=color,
        section=section,
        type=garment_type,
        category=catalog.category_of(garment_type),
        color=estimate_color(color, entry.hex) or estimate_color(entry.color_hint),
        pattern=estimate_pattern(f"{name} {color}"),
        style=estimate_style(name, garment_type),
        season=estimate_season(name, garment_type),
        details=name.lower(),
        brand=brand,
        store_data={"id": entry.id, "ref": entry.ref or None, "snap": snapshot(entry, now)},
    )


def detail_from(store: str, store_data: dict) -> ShopDetail | None:
    """La ficha de un color a partir de la instantánea que guardó el listado. None si no la hay."""
    snap = store_data.get("snap")
    own = str(store_data.get("id") or "")
    if not isinstance(snap, dict) or not own:
        return None
    sizes = snap.get("sizes")
    siblings = []
    for color in snap.get("colors") or []:
        if not isinstance(color, dict) or not color.get("id"):
            continue
        ref = f"{store}:{color['id']}"
        if any(s["product_ref"] == ref for s in siblings):
            continue
        siblings.append({
            "product_ref": ref, "name": color.get("name") or "", "hex": color.get("hex"),
            "url": color.get("url") or "", "store_data": {"id": str(color["id"])},
        })
    if siblings and not any(s["product_ref"] == f"{store}:{own}" for s in siblings):
        siblings = []  # una lista de colores que no incluye el propio no es de fiar
    return ShopDetail(
        price_cents=None,  # el del listado ya está en el producto
        sizes=[{"name": str(name), "in_stock": bool(stock)} for name, stock in sizes] if isinstance(sizes, list) else [],
        photo_urls=[str(p) for p in snap.get("photos") or []][:MAX_PHOTOS],
        description=str(snap.get("desc") or ""),
        color_hex=snap.get("hex"),
        composition=str(snap.get("comp") or ""),
        siblings=siblings if len(siblings) > 1 else None,
        stock_known=isinstance(sizes, list) and bool(sizes),
        sold_out=bool(snap.get("sold_out")),
    )


def page_by_page(key: str, url_of, parse) -> list[ShopProduct]:
    """Una sección que se pagina con la dirección (`?page=2`…) y trae sus datos en el `__NEXT_DATA__` de la
    página (H&M, Weekday): una página cada vez, abierta en el navegador, hasta la última o el tope de la
    tienda (`crawl.max_pages`). `parse(data)` -> (productos, artículos que traía la página, páginas en
    total o None). Si una página siguiente falla, `crawl.Partial` con lo leído."""
    session = browser.require(key)
    found: list[ShopProduct] = []
    refs: set[str] = set()
    limit = max(1, crawl.max_pages(key))
    try:
        for number in range(1, limit + 1):
            crawl.before_page()
            status, data = session.page_json(key, url_of(number))
            if status != 200 or not isinstance(data, dict):
                raise ShopError(f"HTTP {status}")
            products, raw, pages = parse(data)
            crawl.page_read(raw)
            if number == 1 and pages:
                crawl.section_total(min(pages, limit))
            new = [p for p in products if p.product_ref not in refs]
            for product in new:
                refs.add(product.product_ref)
                found.append(product)
            if not raw or (products and not new) or (pages and number >= pages):
                break  # sin más artículos, la misma página otra vez (ya no hay más) o la última
            if len(found) >= crawl.max_products(key):
                break
    except ShopError as exc:
        if not found:
            raise
        raise crawl.Partial(found, exc) from exc
    return found


class ListingConnector:
    """Lo común de las cinco: la ficha sale del listado, sin buscador y sin abrir nunca una ficha."""

    needs_browser = True
    heavy = True  # muchas páginas con navegador: de las pesadas del reparto de noches
    refresh_after_release = False
    language = "fr"
    # Elegir otro color no puede abrir el navegador: solo los colores ya preparados (los que salieron en el
    # listado, con sus fotos bajadas en segundo plano: ver shopping.prepare_colors).
    prepared_colors = True
    domain = ""  # «hm.com»: un enlace de esta tienda en el buscador se explica

    def __init__(self):
        # Las fotos, de su CDN: un cliente normal, con su pausa corta.
        self.fetcher = Fetcher(self.key, pause=0.3, timeout=config.SHOP_TIMEOUT_SECONDS,
                               accept_language="fr-FR,fr;q=0.9")

    def cached_detail(self, store_data: dict) -> ShopDetail | None:
        return detail_from(self.key, store_data)

    def detail(self, store_data: dict) -> ShopDetail | None:
        """Siempre la del listado: la ficha de la tienda no se abre. Sin instantánea no hay nada que dar."""
        found = detail_from(self.key, store_data)
        if found is None:
            raise NeedsBrowser(f"{self.name}: ese color solo se puede ver en la tienda (la app lee su listado "
                               "una vez por semana y no abre sus fichas)")
        return found

    def reference(self, store_data: dict) -> str | None:
        return str(store_data.get("ref") or "") or None

    def search(self, query: str, limit: int = 12) -> list[ShopProduct]:
        """Sin buscador: el navegador no se abre dentro de una petición HTTP. A un enlace de esta tienda se
        le explica por qué; lo demás no es cosa suya."""
        link = _LINK.search(" ".join((query or "").split()))
        if link:
            url = link.group().rstrip(".,;)")
            host = (urlsplit(url if "://" in url else f"https://{url}").hostname or "").lower()
            if host == self.domain or host.endswith("." + self.domain):
                raise SearchError(
                    f"{self.name} solo se lee con navegador en las consultas semanales: el buscador no la abre. "
                    "Actívala en Tiendas y saldrá en Descubrir si está en sus secciones."
                )
        raise NotThisStore("Todavía no sé buscar en esa tienda")

    def download(self, url: str) -> bytes:
        page = self.fetcher.get(url, accept=IMAGE)
        if page.status != 200 or not page.content:
            raise ShopError(f"HTTP {page.status} al bajar la foto")
        return page.content
