"""Conector de Snipes (snipes.com/fr-fr): SOLO zapatillas de hombre, de muchas marcas.

Investigado el 18-11-2026. La plataforma es SCAYLE (la de About You), con la web en Angular:

- Listado CON NAVEGADOR (browser.py): el HTML que pinta el servidor no trae ni el orden por novedad ni la
  paginación; los datos los pide la propia página a su API (`api.snipes.com/.../categories/<id>?page=…`).
  Se abre la página de la sección (`?page=N&sort=new&sortDir=desc`, lo que deja el selector «Nouveautés»)
  y se ESCUCHA esa respuesta, como en Pull&Bear. A esa API no se la llama nunca por cuenta propia.
  24 productos por página; `pagination.totalPages` dice cuántas hay.
- Ficha SIN NAVEGADOR: la página del producto responde a un cliente normal y trae en
  `<script id="ng-state">` la respuesta de `products/<id>` (en gzip + base64). De ahí: el código de
  fabricante (`manufacturerProductCode`, «CW2288-111»), las tallas con su stock, los materiales y los
  otros colores (`siblings`). Así la ficha, el buscador por enlace y elegir otro color funcionan sin
  navegador.
- Fotos de Cloudinary sin modelo en el calzado: `_1` lateral, `_2` tres cuartos, `_3` tres cuartos trasera,
  `_4` suela (fuera), `_5` cenital. Las `_UGC` son fotos de clientes en la calle: fuera siempre.
- Referencia: el código de fabricante (el de la caja); si no se sabe aún, el código de Snipes.
"""
import base64
import gzip
import html
import json
import re
from urllib.parse import urlsplit

from ... import config
from . import browser, crawl
from .base import NotThisStore, SearchError, ShopDetail, ShopError, ShopProduct, old_price
from .estimate import brand_name, estimate_color, estimate_pattern, estimate_season, estimate_shoe_type
from .estimate import estimate_style
from .fetch import IMAGE, Fetcher

BASE = "https://www.snipes.com"
PATH = "/fr-fr"
API = "api.snipes.com"
SORT = "sort=new&sortDir=desc"
PHOTOS = "https://asset.snipes.com/images/f_auto,q_90,w_1600"
# slug -> (nombre para el usuario, ruta, id de la categoría en su API)
CATEGORIES = {
    "chaussures-77": ("Zapatillas y botas", "/c/hommes/chaussures-77", 77),
    "nouveautes-662": ("Novedades", "/c/hommes/nouveautes-662", 662),
}
# Las novedades de calzado ya están dentro de Calzado: con esa activa y leída entera, no se recorren.
COVERED_BY = {"nouveautes-662": ("chaussures-77",)}
MAX_PHOTOS = 4
# Por vista: lateral, tres cuartos, tres cuartos trasera y cenital. La suela (4) nunca.
PHOTO_ORDER = ("1", "2", "3", "5")
SEARCH_RESULTS = 1

_NG_STATE = re.compile(r'<script id="ng-state"[^>]*>(.*?)</script>', re.S)
_NOT_SHOES = re.compile(r"sandale|claquette|\btongs?\b|\bmules?\b|\bslides?\b|chausson|chaussette|\bsocks?\b|"
                        r"\bslippers?\b", re.IGNORECASE)
_PRODUCT_PATH = re.compile(r"/p/([a-z0-9-]+?)-(\d{2,9})/?$")
_LINK_TEXT = re.compile(r"(?:https?://|www\.)\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}/\S*", re.IGNORECASE)
_MEN = {"men", "unisex", "hommes", "unisexe", "mixte"}


def _label(attributes: dict, key: str):
    """El texto de un atributo de SCAYLE: una cadena o, si es múltiple, una lista de cadenas."""
    values = ((attributes or {}).get(key) or {}).get("values")
    if isinstance(values, list):
        return [" ".join(str(v.get("label") or "").split()) for v in values if isinstance(v, dict) and v.get("label")]
    if isinstance(values, dict):
        return " ".join(str(values.get("label") or "").split())
    return ""


def _value(attributes: dict, key: str) -> str:
    values = ((attributes or {}).get(key) or {}).get("values")
    return str(values.get("value") or "") if isinstance(values, dict) else ""


def _text(attributes: dict, key: str) -> str:
    label = _label(attributes, key)
    return ", ".join(label) if isinstance(label, list) else label


def _cents(item: dict) -> int | None:
    price = ((item.get("priceRange") or {}).get("min") or {}).get("withTax")
    return price if isinstance(price, int) and price > 0 else None


def _old_cents(item: dict) -> int | None:
    """El precio de antes de la rebaja: `priceRange.min.beforeSaleWithTax` (céntimos), que la tienda solo
    rellena si está rebajada (visto en los listados guardados: 8000 con 11499 antes)."""
    before = ((item.get("priceRange") or {}).get("min") or {}).get("beforeSaleWithTax")
    return old_price(_cents(item), before)


def product_url(path: str) -> str:
    return f"{BASE}{PATH}{path}" if path.startswith("/") else path


def _is_for_men(attributes: dict) -> bool:
    genders = _label(attributes, "genders")
    genders = genders if isinstance(genders, list) else [genders]
    values = ((attributes or {}).get("genders") or {}).get("values")
    raw = [str(v.get("value") or "") for v in values] if isinstance(values, list) else []
    found = {g.strip().lower() for g in genders + raw if g}
    return not found or bool(found & _MEN)


def make_product(item: dict, section: str) -> ShopProduct | None:
    """Un producto del listado (o la ficha, que trae lo mismo). None si no es calzado de hombre del armario."""
    if not isinstance(item, dict) or item.get("isSoldOut"):
        return None
    attributes = item.get("attributes") or {}
    product_id = str(item.get("id") or "")
    name = " ".join(html.unescape(str(item.get("displayName") or _text(attributes, "name"))).split())
    kind = _text(attributes, "productType")
    shoes = _value(attributes, "productTypeAssortment") in ("shoes", "") and not _NOT_SHOES.search(f"{name} {kind}")
    price = _cents(item)
    path = str(item.get("url") or "")
    if not product_id.isdigit() or not name or not shoes or price is None or not path or not _is_for_men(attributes):
        return None
    shoe_type = estimate_shoe_type(f"{name} {kind}")
    if shoe_type is None:
        return None
    brand = brand_name(_text(attributes, "brand"))
    colour = _text(attributes, "color")
    url = product_url(path)
    return ShopProduct(
        store="snipes",
        product_ref=f"snipes:{product_id}",
        name=name,
        price_cents=price,
        old_price_cents=_old_cents(item),
        old_price_known=True,
        url=url,
        store_color=colour[:1].upper() + colour[1:],
        section=section,
        type=shoe_type,
        category="calzado",
        color=estimate_color(colour),
        pattern=estimate_pattern(name),
        style=estimate_style(f"{name} {kind}", shoe_type),
        season=estimate_season(name, shoe_type),
        details=f"{brand} {name}".strip().lower(),
        brand=brand,
        store_data={"id": product_id, "url": url, "code": str(item.get("referenceKey") or "") or None},
    )


def parse_listing(data: dict, section: str) -> list[ShopProduct]:
    """De la respuesta de `categories/<id>` (la que pide la página) a productos."""
    products: list[ShopProduct] = []
    refs: set[str] = set()
    for item in (data or {}).get("products") or []:
        product = make_product(item, section)
        if product and product.product_ref not in refs:
            refs.add(product.product_ref)
            products.append(product)
    return products


def product_state(page: str, product_id: str | None = None) -> dict | None:
    """La respuesta de `products/<id>` que la ficha trae dentro (`ng-state`, en gzip + base64). None si
    la página no la trae (ya no existe: la tienda lleva a otra)."""
    match = _NG_STATE.search(page or "")
    if not match:
        return None
    try:
        state = json.loads(html.unescape(match.group(1)) if match.group(1).lstrip().startswith("&") else match.group(1))
    except ValueError:
        return None
    keys = [f"Product-{product_id}"] if product_id else []
    keys += [key for key in state if isinstance(key, str) and key.startswith("Product-") and key not in keys]
    for key in keys:
        raw = state.get(key)
        if raw is None:
            continue
        try:
            if isinstance(raw, str):
                raw = json.loads(gzip.decompress(base64.b64decode(raw)))
            body = raw.get("body") if isinstance(raw, dict) and "body" in raw else raw
            body = json.loads(body) if isinstance(body, str) else body
        except (ValueError, OSError, TypeError):
            continue
        if isinstance(body, dict) and body.get("id") is not None and isinstance(body.get("attributes"), dict):
            return body
    return None


def _photos(images: list) -> list[str]:
    by_view: dict[str, str] = {}
    for image in images or []:
        public_id = str((image or {}).get("public_id") or "")
        if not public_id or "_UGC" in public_id.upper():
            continue  # fotos de clientes en la calle, con persona
        view = public_id.rsplit("_", 1)[-1] if "_" in public_id else ""
        by_view.setdefault(view, public_id)
    if "1" not in by_view:
        return []
    order = [v for v in PHOTO_ORDER if v in by_view]
    return [f"{PHOTOS}/{by_view[v]}/p" for v in order][:MAX_PHOTOS]


def _composition(attributes: dict) -> str:
    parts = []
    for key, label in (("outerMaterial", "Dessus"), ("innerMaterial", "Doublure"), ("outerSole", "Semelle"),
                       ("material", "")):
        value = _text(attributes, key)
        if value:
            parts.append(f"{label}: {value}" if label else value)
    return " · ".join(parts)[:300]


def parse_product(body: dict) -> ShopDetail | None:
    """De la ficha (`products/<id>`) a su detalle."""
    if not isinstance(body, dict) or body.get("id") is None:
        return None
    attributes = body.get("attributes") or {}
    sizes, seen = [], set()
    for variant in body.get("variants") or []:
        variant_attributes = (variant or {}).get("attributes") or {}
        name = _text(variant_attributes, "sizeEu") or _text(variant_attributes, "size")
        quantity = ((variant or {}).get("stock") or {}).get("quantity")
        if name and name not in seen:
            seen.add(name)
            sizes.append({"name": name, "in_stock": isinstance(quantity, (int, float)) and quantity > 0})
    siblings = []
    for sibling in body.get("siblings") or []:
        other = str((sibling or {}).get("id") or "")
        path = str((sibling or {}).get("url") or "")
        if not other.isdigit() or not path or sibling.get("isSoldOut") or \
                any(s["product_ref"] == f"snipes:{other}" for s in siblings):
            continue
        colour = _text(sibling.get("attributes") or {}, "color")
        url = product_url(path)
        siblings.append({
            "product_ref": f"snipes:{other}", "name": colour[:1].upper() + colour[1:], "hex": None, "url": url,
            "store_data": {"id": other, "url": url},
        })
    code = _text(attributes, "manufacturerProductCode")
    colour = _text(attributes, "color")
    return ShopDetail(
        price_cents=_cents(body),
        old_price_cents=_old_cents(body),
        old_price_known=True,
        sizes=sizes,
        photo_urls=_photos(body.get("images") or []),
        description=" ".join(html.unescape(re.sub(r"<[^>]+>", " ", _text(attributes, "description"))).split())[:400],
        composition=_composition(attributes),
        siblings=sorted(siblings, key=lambda s: s["product_ref"]) if len(siblings) > 1 else [],
        store_color=colour[:1].upper() + colour[1:],
        store_data={"mpn": code} if code else {},
    )


def reference(store_data: dict) -> str | None:
    """El código de fabricante («CW2288-111»); si aún no se ha leído la ficha, el código de Snipes."""
    return str(store_data.get("mpn") or store_data.get("code") or "") or None


def parse_query(text: str) -> tuple[str, str]:
    """(ruta en la web francesa, número de producto) de un enlace de Snipes (de cualquier país). Lanza NotThisStore con cualquier otra cosa: su
    buscador no tiene una ruta que se haya podido comprobar."""
    text = " ".join((text or "").split())
    link = _LINK_TEXT.search(text)
    if not link:
        raise NotThisStore("Snipes solo busca por enlace de producto")
    url = link.group().rstrip(".,;)")
    parts = urlsplit(url if "://" in url else f"https://{url}")
    host = (parts.hostname or "").lower()
    if host != "snipes.com" and not host.endswith(".snipes.com"):
        raise NotThisStore("Todavía no sé buscar en esa tienda")
    match = _PRODUCT_PATH.search(parts.path)
    if not match:
        raise SearchError("Ese enlace de Snipes no es el de un producto: pega el de la página de la zapatilla")
    return f"/p/{match.group(1)}-{match.group(2)}", match.group(2)


def page_url(path: str, number: int) -> str:
    """La página `number` (desde 1) de una sección, de lo más nuevo a lo más viejo."""
    return f"{BASE}{PATH}{path}?page={number}&{SORT}"


class SnipesConnector:
    key = "snipes"
    name = "Snipes"
    needs_browser = True  # el listado; la ficha y las fotos van sin navegador
    heavy = False  # una sección de zapatillas: con navegador, pero ligera
    # No se sabe qué día saca novedades: los sábados (reparto de noches, ver shops/__init__.py).
    refresh_weekday = 5
    refresh_after_release = False
    language = "fr"
    categories = {slug: label for slug, (label, _path, _id) in CATEGORIES.items()}
    covered_by = COVERED_BY
    section_types = {slug: "zapatillas" for slug in CATEGORIES}

    def __init__(self, pause: float | None = None):
        self.fetcher = Fetcher("snipes", pause=max(config.SHOP_PAUSE_SECONDS, 3.0) if pause is None else pause,
                               timeout=config.SHOP_TIMEOUT_SECONDS, accept_language="fr-FR,fr;q=0.9")

    def _is_listing(self, url: str, category_id: int) -> bool:
        return API in url and f"/categories/{category_id}?" in url

    def list_category(self, slug: str) -> list[ShopProduct]:
        """La sección entera, de 24 en 24 y de lo más nuevo a lo más viejo: cada página se abre en el
        navegador y se lee la respuesta que pide ella misma. Si una siguiente falla, `crawl.Partial`."""
        _label, path, category_id = CATEGORIES[slug]
        session = browser.require(self.key)
        products: list[ShopProduct] = []
        refs: set[str] = set()
        pages = None
        try:
            for number in range(1, max(1, crawl.max_pages(self.key)) + 1):
                if pages is not None and number > pages:
                    break
                crawl.before_page()
                responses = session.open(
                    self.key, page_url(path, number),
                    want=lambda url: self._is_listing(url, category_id),
                    ready=lambda urls: any(self._is_listing(url, category_id) for url in urls),
                )
                found = [r.data for r in responses if r.status == 200 and isinstance(r.data, dict) and "products" in r.data]
                # La de esta página (la web puede pedir también otra cosa de la misma categoría).
                data = next((d for d in reversed(found) if (d.get("pagination") or {}).get("currentPage") == number - 1),
                            found[-1] if found else None)
                if data is None:
                    raise ShopError("la respuesta no era la esperada (sin listado)")
                pagination = data.get("pagination") or {}
                if pages is None and isinstance(pagination.get("totalPages"), int):
                    pages = max(1, pagination["totalPages"])
                    crawl.section_total(min(pages, crawl.max_pages(self.key)))
                before = len(products)
                for product in parse_listing(data, slug):
                    if product.product_ref not in refs:
                        refs.add(product.product_ref)
                        products.append(product)
                crawl.page_read(len(products) - before)
                if not data.get("products") or len(products) >= crawl.max_products(self.key):
                    break
        except ShopError as exc:
            if not products:
                raise
            raise crawl.Partial(products, exc) from exc
        return products

    def _body(self, url: str, product_id: str) -> dict | None:
        page = self.fetcher.get(url)
        if page.status in (404, 410):
            return None
        if page.status != 200:
            raise ShopError(f"HTTP {page.status}")
        return product_state(page.text, product_id)

    def detail(self, store_data: dict) -> ShopDetail | None:
        product_id = str(store_data.get("id") or "")
        url = str(store_data.get("url") or "")
        if not product_id.isdigit() or not url.startswith(BASE + "/"):
            return None
        body = self._body(url, product_id)
        return parse_product(body) if body else None

    def reference(self, store_data: dict) -> str | None:
        return reference(store_data)

    def maker_code(self, store_data: dict) -> str | None:
        return str(store_data.get("mpn") or "") or None

    def search(self, query: str, limit: int = 12) -> list[ShopProduct]:
        path, product_id = parse_query(query)
        body = self._body(product_url(path), product_id)
        product = make_product(body, "") if body else None
        if product is None:
            raise SearchError("No he encontrado esa zapatilla en Snipes (o no es de hombre)")
        detail = parse_product(body)
        if detail and detail.store_data.get("mpn"):
            product.store_data["mpn"] = detail.store_data["mpn"]
        return [product][: max(1, min(limit, SEARCH_RESULTS))]

    def download(self, url: str) -> bytes:
        page = self.fetcher.get(url, accept=IMAGE, pause=0.5)
        if page.status != 200 or not page.content:
            raise ShopError(f"HTTP {page.status} al bajar la foto")
        return page.content
