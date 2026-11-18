"""Conector de Carhartt WIP (carhartt-wip.com/fr-fr): ropa y zapatillas de hombre.

Sin navegador (investigado el 18-11-2026: httpx con cabeceras normales, ~16 peticiones sin un rechazo;
Vercel, sin antibots a la vista). Si un día deja de responder a un cliente normal, basta con
`needs_browser = True`: las páginas se leen igual, abiertas en el navegador (ver fetch.read_html).

- Next.js (app router): los datos van en el flujo RSC del HTML, trozos `self.__next_f.push([1,"…"])`. Se
  juntan y de ahí se sacan las tarjetas (`["$","$L…","<productKey>",{"locale":…}]`) con nombre, precio,
  color, fotos y `categoryUrlAnalytics` («men-jackets-shirt»: las sobrecamisas van dentro de Chaquetas).
  Es más frágil que un JSON entero: si cambian la forma, sale «la respuesta no era la esperada».
- Paginación `?page=N`, 48 por página; el total, en `productsCount`. El orden por defecto ya es «nuevo».
- Ficha: la página del producto (`/fr-fr/p/<slug>`): tallas con unidades en stock (`mainProductSizes`),
  los otros colores («Couleurs disponibles») y la composición (bloque «Matières & Entretien»), más el
  ld+json del producto (precio, disponibilidad, fotos).
- Fotos: `ST-01` delante y `ST-02` detrás, sin modelo (CDN Amplience); `OF-…` llevan modelo.
- Nombres y colores en inglés («Hooded Tyson Jacket», «Duck Blue»): se traducen como los demás.
- Referencia: el modelo («I037783»), el de la etiqueta.
- Sin buscador utilizable (la web busca en el cliente con un servicio de terceros, que no se usa): solo
  enlaces de producto.
"""
import html as htmllib
import json
import re
from urllib.parse import urlsplit

from ... import catalog, config
from . import crawl
from .base import NotThisStore, SearchError, ShopDetail, ShopError, ShopProduct
from .estimate import estimate_color, estimate_pattern, estimate_season, estimate_style, estimate_type
from .fetch import IMAGE, Fetcher, read_html

BASE = "https://www.carhartt-wip.com"
PATH = "/fr-fr"
CDN = "https://cdn.media.amplience.net/i/carhartt_wip"
PAGE_SIZE = 48
PHOTO = "$ST$&w=1280&fmt=jpg"
# slug -> (nombre para el usuario, tipo por defecto)
CATEGORIES = {
    "homme-tshirts-et-polos": ("Camisetas y polos", "camiseta"),
    "homme-chemises": ("Camisas", "camisa"),
    "homme-sweats": ("Sudaderas", "sudadera"),
    "homme-mailles": ("Punto", "jersey"),
    "homme-vestes-et-manteaux": ("Chaquetas, abrigos y sobrecamisas", "chaqueta"),
    "homme-pantalons": ("Pantalones", "pantalón"),
    "homme-denim": ("Vaqueros", "vaquero"),
    "homme-shorts": ("Bermudas", "pantalón corto"),
    "homme-chaussures": ("Zapatillas", "zapatillas"),
}

_PUSH = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', re.S)
_TILE = re.compile(r'\["\$","\$L[0-9a-z]+","([A-Z0-9_]+)",\{"locale"')
_COUNT = re.compile(r'"productsCount":(\d+)')
_LD_JSON = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
_MATERIAL = re.compile(r'\["\$","li","(?!careInstructions)[A-Za-z0-9-]+",\{"children":\["\$","span",null,\{[^{}]*?"children":"([^"]+)"')
_LINK_TEXT = re.compile(r"(?:https?://|www\.)\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}/\S*", re.IGNORECASE)
_DECODER = json.JSONDecoder()


def flight(page: str) -> str:
    """El flujo RSC de la página, junto y decodificado."""
    parts = []
    for chunk in _PUSH.findall(page or ""):
        try:
            parts.append(json.loads(f'"{chunk}"'))
        except ValueError:
            continue
    return "".join(parts)


def tiles(stream: str) -> list[dict]:
    """Las tarjetas de producto del flujo, sin repetir."""
    found, seen = [], set()
    for match in _TILE.finditer(stream):
        try:
            data, _end = _DECODER.raw_decode(stream, match.end() - len('{"locale"'))
        except ValueError:
            continue
        key = data.get("productKey") if isinstance(data, dict) else None
        if key and key not in seen:
            seen.add(key)
            found.append(data)
    return found


def _after(stream: str, marker: str):
    index = stream.find(marker)
    if index < 0:
        return None
    try:
        return _DECODER.raw_decode(stream, index + len(marker))[0]
    except ValueError:
        return None


def _cents(value) -> int | None:
    try:
        cents = round(float(value) * 100)
    except (TypeError, ValueError):
        return None
    return cents if cents > 0 else None


def _type(name: str, analytics: str, section: str) -> str | None:
    """El tipo: lo que diga el nombre; si no, la sección. Las «Shirt Jac» (sobrecamisas) van en Chaquetas,
    un pantalón de la sección Denim es un vaquero y una «Jacket» de Sudaderas, una sudadera con cremallera."""
    default = CATEGORIES.get(section, (None, None))[1]
    analytics = (analytics or "").lower()
    if analytics.endswith("-shirt") and "jacket" in analytics:
        return "sobrecamisa"
    if "denim" in analytics or section == "homme-denim":
        default = "vaquero"
    garment_type = estimate_type(name, default)
    if garment_type == "chaqueta" and (section == "homme-sweats" or "sweat" in analytics):
        return "sudadera"  # «Hooded American Script Jacket» en Sudaderas: una sudadera con cremallera
    if garment_type == "pantalón" and default == "vaquero":
        return "vaquero"
    return garment_type


def model_of(key: str) -> str:
    """«I037783_89_XX» -> «I037783»: el modelo, el de la etiqueta."""
    return (key or "").split("_")[0]


def make_product(tile: dict, section: str) -> ShopProduct | None:
    """Una tarjeta del listado. None si no cabe en el armario o está agotada."""
    key = str(tile.get("productKey") or "")
    slug = str(tile.get("slug") or "")
    if not key or not slug or tile.get("isSoldOut") or tile.get("isComingSoon"):
        return None
    colour = " ".join(str(tile.get("colorFinishDescription") or "").split())
    full = " ".join(str(tile.get("fullName") or "").split())
    name = full[: -len(colour)].strip(" ,") if colour and full.endswith(colour) else ""
    name = name or " ".join(str(tile.get("productTitle") or "").split())
    discounted = tile.get("discountedPrice")
    price = _cents(discounted) if isinstance(discounted, (int, float)) else None
    price = price or _cents(tile.get("price"))
    garment_type = _type(name, str(tile.get("categoryUrlAnalytics") or ""), section)
    if not name or garment_type is None or price is None:
        return None
    url = f"{BASE}{PATH}/p/{slug}"
    return ShopProduct(
        store="carhartt",
        product_ref=f"carhartt:{key}",
        name=name,
        price_cents=price,
        url=url,
        store_color=colour[:60],
        section=section,
        type=garment_type,
        category=catalog.category_of(garment_type),
        color=estimate_color(colour),
        pattern=estimate_pattern(f"{name} {colour}"),
        style=estimate_style(name, garment_type),
        season=estimate_season(name, garment_type),
        details=f"{name} {tile.get('categoryUrlAnalytics') or ''}".strip().lower(),
        store_data={"key": key, "slug": slug, "model": model_of(key)},
    )


def parse_listing(page: str, section: str) -> tuple[list[ShopProduct], int | None]:
    """(productos, total de la sección) de una página del listado."""
    stream = flight(page)
    if not stream:
        raise ShopError("la respuesta no era la esperada (sin datos de la página)")
    count = _COUNT.search(stream)
    products: list[ShopProduct] = []
    refs: set[str] = set()
    for tile in tiles(stream):
        product = make_product(tile, section)
        if product and product.product_ref not in refs:
            refs.add(product.product_ref)
            products.append(product)
    return products, int(count.group(1)) if count else None


def _ld_product(page: str) -> dict:
    for match in _LD_JSON.finditer(page or ""):
        try:
            data = json.loads(match.group(1))
        except ValueError:
            continue
        for node in (data.get("@graph") if isinstance(data, dict) and "@graph" in data else [data]):
            if isinstance(node, dict) and node.get("@type") == "Product":
                return node
    return {}


def _photos(key: str, images: list) -> tuple[list[str], bool]:
    """Delante (ST-01) y detrás (ST-02) sin modelo; si no las hay, la primera con modelo (y True)."""
    names = " ".join(str(i) for i in images or [])
    shots = [f"{CDN}/{key}-{view}?{PHOTO}" for view in ("ST-01", "ST-02") if f"{key}-{view}" in names]
    if shots:
        return shots, False
    first = next((str(i).split("?")[0] for i in images or [] if f"{key}-OF-" in str(i)), None)
    return ([f"{first}?$OF$&w=1280&fmt=jpg"] if first else []), bool(first)


def parse_product(page: str, key: str) -> ShopDetail | None:
    """De la página de un producto a su detalle. None si no es una ficha (ya no existe)."""
    stream = flight(page)
    ld = _ld_product(page)
    sizes_raw = _after(stream, '"mainProductSizes":')
    if not ld and not isinstance(sizes_raw, list):
        return None
    sizes = []
    for size in sizes_raw or []:
        name = str((size or {}).get("name") or "").strip()
        units = size.get("inStock") if isinstance(size, dict) else None
        if name:
            sizes.append({"name": name, "in_stock": (units or 0) > 0 if isinstance(units, (int, float)) else bool(units)})
    options = _after(stream, '"label":"Couleurs disponibles","options":') or []
    siblings = []
    for option in options if isinstance(options, list) else []:
        other = str((option or {}).get("key") or "")
        slug = str((option or {}).get("slug") or "")
        if not other or not slug or option.get("isSoldOut"):
            continue
        url = f"{BASE}{PATH}/p/{slug}"
        siblings.append({
            "product_ref": f"carhartt:{other}", "name": str(option.get("colorName") or ""), "hex": None, "url": url,
            "store_data": {"key": other, "slug": slug, "model": model_of(other)},
        })
    selected = next((o for o in options if isinstance(o, dict) and o.get("isSelected")), None) if isinstance(options, list) else None
    key = str((selected or {}).get("key") or key)
    material_at = stream.find("accordion-materialAndCare-description")
    materials = _MATERIAL.findall(stream[material_at: material_at + 6000]) if material_at >= 0 else []
    offers = ld.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    photos, model = _photos(key, ld.get("image") if isinstance(ld.get("image"), list) else [ld.get("image")])
    if not sizes and "InStock" in str(offers.get("availability") or ""):
        sizes = [{"name": str(s), "in_stock": True} for s in ld.get("size") or []]
    return ShopDetail(
        price_cents=_cents(offers.get("price")),
        sizes=sizes,
        photo_urls=photos,
        description=" ".join(htmllib.unescape(str(ld.get("description") or "")).split())[:400],
        composition=" · ".join(dict.fromkeys(m.strip() for m in materials if m.strip()))[:300]
        or " ".join(str(ld.get("material") or "").split())[:300],
        siblings=sorted(siblings, key=lambda s: s["product_ref"]) if len(siblings) > 1 else [],
        store_color=(selected or {}).get("colorName") or str(ld.get("color") or ""),
        store_data={"model_photo": True} if model else {},
    )


def reference(store_data: dict) -> str | None:
    """El modelo («I037783»), el de la etiqueta y las fotos."""
    return str(store_data.get("model") or model_of(str(store_data.get("key") or ""))) or None


def parse_query(text: str) -> str:
    """El slug de un enlace de producto de Carhartt WIP. Lanza NotThisStore con cualquier otra cosa: la
    web no tiene un buscador que se pueda usar sin su servicio de terceros."""
    text = " ".join((text or "").split())
    link = _LINK_TEXT.search(text)
    if not link:
        raise NotThisStore("Carhartt WIP solo busca por enlace de producto")
    url = link.group().rstrip(".,;)")
    parts = urlsplit(url if "://" in url else f"https://{url}")
    host = (parts.hostname or "").lower()
    if host != "carhartt-wip.com" and not host.endswith(".carhartt-wip.com"):
        raise NotThisStore("Todavía no sé buscar en esa tienda")
    match = re.search(r"/p/([a-z0-9-]+)", parts.path)
    if not match:
        raise SearchError("Ese enlace de Carhartt WIP no es el de un producto: pega el de la página de la prenda")
    return match.group(1)


class CarharttConnector:
    key = "carhartt"
    name = "Carhartt WIP"
    needs_browser = False  # True si deja de responder a un cliente normal: ver fetch.read_html
    heavy = False
    # No se sabe qué día saca novedades: los miércoles (reparto de noches, ver shops/__init__.py).
    refresh_weekday = 2
    refresh_after_release = False
    language = "fr"
    categories = {slug: label for slug, (label, _type) in CATEGORIES.items()}
    section_types = {slug: garment_type for slug, (_label, garment_type) in CATEGORIES.items()}

    def __init__(self, pause: float | None = None):
        self.fetcher = Fetcher("carhartt", pause=max(config.SHOP_PAUSE_SECONDS, 3.0) if pause is None else pause,
                               timeout=max(config.SHOP_TIMEOUT_SECONDS, 40.0), accept_language="fr-FR,fr;q=0.9")

    def _html(self, url: str) -> str | None:
        status, text = read_html(self, url)
        if status in (404, 410):
            return None
        if status != 200:
            raise ShopError(f"HTTP {status}")
        return text

    def list_category(self, slug: str) -> list[ShopProduct]:
        """La sección entera, de 48 en 48 (`?page=N`), hasta la última página (o el tope)."""
        products: list[ShopProduct] = []
        refs: set[str] = set()
        pages = None
        try:
            for number in range(1, max(1, crawl.max_pages(self.key)) + 1):
                if pages is not None and number > pages:
                    break
                crawl.before_page()
                page = self._html(f"{BASE}{PATH}/c/{slug}" + (f"?page={number}" if number > 1 else ""))
                if page is None:
                    raise ShopError("HTTP 404")
                found, total = parse_listing(page, slug)
                if pages is None and total is not None:
                    pages = max(1, -(-total // PAGE_SIZE))
                    crawl.section_total(min(pages, crawl.max_pages(self.key)))
                before = len(products)
                for product in found:
                    if product.product_ref not in refs:
                        refs.add(product.product_ref)
                        products.append(product)
                crawl.page_read(len(products) - before)
                if number == 1 and not found and total is None:
                    raise ShopError("la respuesta no era la esperada (sin productos)")
                if not found or len(products) >= crawl.max_products(self.key):
                    break
        except ShopError as exc:
            if not products:
                raise
            raise crawl.Partial(products, exc) from exc
        return products

    def detail(self, store_data: dict) -> ShopDetail | None:
        slug = str(store_data.get("slug") or "")
        if not re.fullmatch(r"[a-z0-9-]+", slug):
            return None
        page = self._html(f"{BASE}{PATH}/p/{slug}")
        return parse_product(page, str(store_data.get("key") or "")) if page else None

    def reference(self, store_data: dict) -> str | None:
        return reference(store_data)

    def search(self, query: str, limit: int = 12) -> list[ShopProduct]:
        slug = parse_query(query)
        page = self._html(f"{BASE}{PATH}/p/{slug}")
        stream = flight(page) if page else ""
        ld = _ld_product(page or "")
        options = _after(stream, '"label":"Couleurs disponibles","options":') or []
        selected = next((o for o in options if isinstance(o, dict) and o.get("isSelected")), None) if isinstance(options, list) else None
        offers = ld.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        if not ld or not selected:
            raise SearchError("No he encontrado esa prenda en Carhartt WIP")
        colour = str(selected.get("colorName") or ld.get("color") or "")
        tile = {
            "productKey": selected.get("key"), "slug": slug, "colorFinishDescription": colour,
            "fullName": f"{ld.get('name') or ''} {colour}".strip(), "productTitle": ld.get("name"),
            "price": offers.get("price"), "categoryUrlAnalytics": "",
        }
        product = make_product(tile, "")
        if product is None:
            raise SearchError("Eso no es una prenda que quepa en el armario")
        return [product]

    def download(self, url: str) -> bytes:
        page = self.fetcher.get(url, accept=IMAGE, pause=0.5)
        if page.status != 200 or not page.content:
            raise ShopError(f"HTTP {page.status} al bajar la foto")
        return page.content
