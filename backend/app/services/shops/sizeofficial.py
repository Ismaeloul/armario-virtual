"""Conector de size? (sizeofficial.fr): SOLO zapatillas de hombre, de muchas marcas.

Se lee CON NAVEGADOR (browser.py): a un cliente normal las colecciones y las fichas le responden 429 a la
primera petición; a un Chromium de serie con su ventana, no (investigado el 18-11-2026). La tienda está en
Shopify (no es la plataforma de JD Sports, aunque comparte sus números de producto).

- Listado: la página de la colección (`/collections/chaussures-hommes?page=N`, 48 por página) pide su
  listado a un buscador de terceros (Bloomreach). NO se le llama nunca por cuenta propia: se ESCUCHA la
  respuesta que pide la propia página al cargarse, como en Pull&Bear. `numFound` dice cuántos hay.
  Novedades (`nouveautes-chaussures-hommes`) va dentro de Zapatillas (`covered_by`).
- Ficha: la página del producto, abierta en el navegador: su JSON-LD (nombre, color, precio y, al final
  de la descripción tras « | », el código de fabricante: «… | LA2249») y la lista de variantes de Shopify
  (las tallas, con si quedan).
- Fotos: solo la `_a` (lateral, sin persona) es fiable como foto de producto; las demás cambian de un
  producto a otro (la zapatilla puesta, fotos de ambiente). Se baja de la CDN de Shopify, que responde a
  un cliente normal.
- Sin buscador: el navegador no se abre dentro de una petición HTTP.
"""
import html
import json
import math
import re
from urllib.parse import urlsplit

from ... import config
from . import browser, crawl
from .base import NeedsBrowser, NotThisStore, SearchError, ShopDetail, ShopError, ShopProduct
from .estimate import brand_name, estimate_color, estimate_pattern, estimate_season, estimate_shoe_type
from .estimate import estimate_style
from .fetch import IMAGE, Fetcher

BASE = "https://www.sizeofficial.fr"
LISTING = "core.dxpapi.com/api/v1/core/"
PER_PAGE = 48
PHOTO_WIDTH = 1600
# slug (la colección de Shopify) -> nombre para el usuario
CATEGORIES = {
    "chaussures-hommes": "Zapatillas y botas",
    "nouveautes-chaussures-hommes": "Novedades",
}
COVERED_BY = {"nouveautes-chaussures-hommes": ("chaussures-hommes",)}

_LD_JSON = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
_JSON_SCRIPT = re.compile(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', re.S)
_NOT_SHOES = re.compile(r"sandale|claquette|\btongs?\b|\bmules?\b|\bslides?\b|chausson|chaussette|\bsocks?\b|"
                        r"\bslippers?\b|\bsandals?\b|\bclogs?\b", re.IGNORECASE)
_EXCLUSIVE = re.compile(r"\s*[-–]\s*size\?\s*(exclusive|exclusivit[ée])\s*$", re.IGNORECASE)
_IMAGE_REF = re.compile(r"/sz_([A-Za-z0-9]+)_([a-z])\.(?:jpg|png|webp)", re.IGNORECASE)
_CODE_TAIL = re.compile(r"\|\s*([A-Z0-9][A-Z0-9-]{3,19})\s*$")
_PRODUCT_PATH = re.compile(r"/products/([A-Za-z0-9-]+)")
_LINK_TEXT = re.compile(r"(?:https?://|www\.)\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}/\S*", re.IGNORECASE)
_SUBBRANDS = ("originals", "sportswear")
# Los circulitos de color de la ficha: un enlace por color, con su nombre y la miniatura de su foto `_a`.
_SWATCH = re.compile(r'<a [^>]*class="js-sp-swatch"[^>]*>(.*?)</a>', re.S)
_ATTR = re.compile(r'(data-handle|data-label)="([^"]*)"')
CDN_FILES = "https://cdn.shopify.com/s/files/1/0921/0911/1619/files"


def _clean_name(title: str, brand: str) -> str:
    """«adidas Originals Kegler Super GORE-TEX - size? exclusive» -> «Kegler Super GORE-TEX»."""
    name = _EXCLUSIVE.sub("", " ".join(html.unescape(title or "").split()))
    low = name.lower()
    if brand and low.startswith(brand.lower() + " ") and len(name) > len(brand) + 2:
        name = name[len(brand) + 1:]
        if name.lower().split(" ", 1)[0] in _SUBBRANDS and " " in name:
            name = name.split(" ", 1)[1]
    return name


def _photo(url: str) -> str:
    return f"{url.split('?')[0]}?width={PHOTO_WIDTH}"


def _side_photo(images: list) -> str | None:
    """La foto `_a` (lateral, sin persona) de la lista, en la CDN de Shopify."""
    for url in images or []:
        match = _IMAGE_REF.search(str(url or ""))
        if match and match.group(2).lower() == "a" and str(url).startswith("https://cdn.shopify.com/"):
            return str(url).split("?")[0]
    return None


def make_product(doc: dict, section: str) -> ShopProduct | None:
    """Un producto del listado (un «doc» de la respuesta). None si no es calzado del armario o no queda talla."""
    if not isinstance(doc, dict):
        return None
    handle = str(doc.get("handle") or "")
    title = str(doc.get("title") or "")
    brand = brand_name(str(doc.get("brand") or ""))
    price = doc.get("sale_price")
    variants = doc.get("variants") or []
    available = any("true" in [str(v).lower() for v in (variant or {}).get("availableForSale") or []]
                    for variant in variants)
    try:
        cents = round(float(price) * 100)
    except (TypeError, ValueError):
        return None
    name = _clean_name(title, brand)
    if not re.fullmatch(r"[A-Za-z0-9-]+", handle) or not name or cents <= 0 or _NOT_SHOES.search(title):
        return None
    if variants and not available:
        return None
    shoe_type = estimate_shoe_type(title)
    if shoe_type is None:
        return None
    url = f"{BASE}/products/{handle}"
    side = _side_photo(doc.get("images") or [])
    ref = _IMAGE_REF.search(side).group(1) if side else None
    return ShopProduct(
        store="size",
        product_ref=f"size:{handle}",
        name=name,
        price_cents=cents,
        url=url,
        store_color="",  # el listado no dice el color: sale en la ficha
        section=section,
        type=shoe_type,
        category="calzado",
        color=estimate_color(""),
        pattern=estimate_pattern(name),
        style=estimate_style(name, shoe_type),
        season=estimate_season(name, shoe_type),
        details=f"{brand} {name}".strip().lower(),
        brand=brand,
        store_data={"handle": handle, "ref": ref, "img": side, "new": str(doc.get("item_isnew") or "").lower() == "true"},
    )


def listing_response(data: dict) -> dict | None:
    """El bloque `response` de la respuesta del buscador ({numFound, start, docs})."""
    response = (data or {}).get("response") if isinstance(data, dict) else None
    return response if isinstance(response, dict) and isinstance(response.get("docs"), list) else None


def parse_listing(data: dict, section: str) -> list[ShopProduct]:
    products: list[ShopProduct] = []
    refs: set[str] = set()
    for doc in (listing_response(data) or {}).get("docs") or []:
        product = make_product(doc, section)
        if product and product.product_ref not in refs:
            refs.add(product.product_ref)
            products.append(product)
    return products


def _ld_product(page: str) -> dict | None:
    for match in _LD_JSON.finditer(page or ""):
        try:
            data = json.loads(match.group(1))
        except ValueError:
            continue
        for node in (data.get("@graph") if isinstance(data, dict) and "@graph" in data else [data]):
            if isinstance(node, dict) and node.get("@type") == "Product":
                return node
    return None


def _variants(page: str) -> list[dict]:
    """La lista de variantes de Shopify que trae la ficha (una por talla)."""
    for match in _JSON_SCRIPT.finditer(page or ""):
        body = match.group(1).strip()
        if not body.startswith("[") or '"option1"' not in body:
            continue
        try:
            data = json.loads(body)
        except ValueError:
            continue
        if isinstance(data, list) and all(isinstance(v, dict) for v in data):
            return data
    return []


def maker_code_of(description: str) -> str | None:
    """El código de fabricante que size? pone al final de la descripción: «… | LA2249»."""
    match = _CODE_TAIL.search(" ".join(html.unescape(description or "").split()))
    code = match.group(1) if match else None
    return code if code and re.search(r"\d", code) else None


def parse_product_page(page: str, store_data: dict | None = None) -> ShopDetail | None:
    """De la ficha a su detalle. None si la página no es la de un producto."""
    product = _ld_product(page)
    if not product:
        return None
    offers = product.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    try:
        price = round(float(str(offers.get("price") or "").replace(",", ".")) * 100)
    except ValueError:
        price = None
    sizes, seen = [], set()
    for variant in _variants(page):
        name = " ".join(str(variant.get("option1") or variant.get("title") or "").split())
        if name and name not in seen:
            seen.add(name)
            sizes.append({"name": name, "in_stock": bool(variant.get("available"))})
    description = " ".join(html.unescape(str(product.get("description") or "")).split())
    code = maker_code_of(description)
    text = description.rsplit(" | ", 1)[0] if code else description
    images = product.get("image") or []
    images = images if isinstance(images, list) else [images]
    side = (store_data or {}).get("img")
    if not side:
        # La de la ficha está en el dominio de la tienda (que limita a un cliente normal): la misma, en la CDN.
        match = next((m for m in (_IMAGE_REF.search(str(i)) for i in images) if m and m.group(2).lower() == "a"), None)
        side = (f"{CDN_FILES}/sz_{match.group(1)}_a.jpg" if match else None)
    colour = " ".join(str(product.get("color") or "").split())
    return ShopDetail(
        price_cents=price if price and price > 0 else None,
        sizes=sizes,
        photo_urls=[_photo(side)] if side else [],
        description=text[:400],
        siblings=siblings_of(page),
        store_color=colour[:1].upper() + colour[1:],
        store_data={"mpn": code} if code else {},
        stock_known=bool(sizes),
        sold_out=not sizes and "InStock" not in str(offers.get("availability") or ""),
    )


def siblings_of(page: str) -> list[dict]:
    """Los colores del modelo, de los circulitos de la ficha (el propio incluido). [] si solo hay uno."""
    siblings = []
    for match in _SWATCH.finditer(page or ""):
        tag = page[match.start(): page.index(">", match.start()) + 1]
        attrs = dict(_ATTR.findall(tag))
        handle = attrs.get("data-handle") or ""
        photo = _IMAGE_REF.search(match.group(1))
        if not re.fullmatch(r"[A-Za-z0-9-]+", handle) or any(s["product_ref"] == f"size:{handle}" for s in siblings):
            continue
        url = f"{BASE}/products/{handle}"
        img = f"{CDN_FILES}/sz_{photo.group(1)}_a.jpg" if photo else None
        siblings.append({
            "product_ref": f"size:{handle}", "name": html.unescape(attrs.get("data-label") or "").strip().capitalize(),
            "hex": None, "url": url, "store_data": {"handle": handle, "img": img, "ref": photo.group(1) if photo else None},
        })
    return sorted(siblings, key=lambda s: s["product_ref"]) if len(siblings) > 1 else []


def reference(store_data: dict) -> str | None:
    """El código de fabricante («LA2249») si ya se leyó la ficha; si no, el número de size?."""
    return str(store_data.get("mpn") or store_data.get("handle") or "") or None


def parse_query(text: str) -> str:
    """El número de producto de un enlace de size?. Lanza NotThisStore con cualquier otra cosa."""
    text = " ".join((text or "").split())
    link = _LINK_TEXT.search(text)
    if not link:
        raise NotThisStore("size? solo busca por enlace de producto")
    url = link.group().rstrip(".,;)")
    parts = urlsplit(url if "://" in url else f"https://{url}")
    host = (parts.hostname or "").lower()
    if not re.fullmatch(r"(?:[a-z0-9-]+\.)*(?:sizeofficial\.[a-z.]{2,6}|size\.co\.uk)", host):
        raise NotThisStore("Todavía no sé buscar en esa tienda")
    match = _PRODUCT_PATH.search(parts.path)
    if not match:
        raise SearchError("Ese enlace de size? no es el de un producto: pega el de la página de la zapatilla")
    return match.group(1)


class SizeConnector:
    key = "size"
    name = "size?"
    needs_browser = True
    heavy = False  # una sección de zapatillas: con navegador, pero ligera
    # No se sabe qué día saca novedades: los domingos (reparto de noches, ver shops/__init__.py).
    refresh_weekday = 6
    refresh_after_release = False
    language = "fr"
    categories = dict(CATEGORIES)
    covered_by = COVERED_BY
    section_types = {slug: "zapatillas" for slug in CATEGORIES}
    prepared_colors = True

    def __init__(self):
        # Las fotos, de la CDN de Shopify: un cliente normal, con su pausa corta.
        self.fetcher = Fetcher("size", pause=0.5, timeout=config.SHOP_TIMEOUT_SECONDS, accept_language="fr-FR,fr;q=0.9")

    def list_category(self, slug: str) -> list[ShopProduct]:
        """La colección entera, de 48 en 48: cada página se abre en el navegador y se lee el listado que
        pide ella misma. Si una siguiente falla, `crawl.Partial` con lo leído."""
        session = browser.require(self.key)
        products: list[ShopProduct] = []
        refs: set[str] = set()
        pages = None
        try:
            for number in range(1, max(1, crawl.max_pages(self.key)) + 1):
                if pages is not None and number > pages:
                    break
                crawl.before_page()
                url = f"{BASE}/collections/{slug}" + (f"?page={number}" if number > 1 else "")
                responses = session.open(self.key, url, want=lambda u: LISTING in u,
                                         ready=lambda urls: any(LISTING in u for u in urls))
                found = [listing_response(r.data) for r in responses if r.status == 200]
                found = [f for f in found if f is not None]
                start = (number - 1) * PER_PAGE
                data = next((f for f in reversed(found) if f.get("start") == start), found[-1] if found else None)
                if data is None:
                    raise ShopError("la respuesta no era la esperada (sin listado)")
                if pages is None and isinstance(data.get("numFound"), int):
                    pages = max(1, math.ceil(data["numFound"] / PER_PAGE))
                    crawl.section_total(min(pages, crawl.max_pages(self.key)))
                before = len(products)
                for product in parse_listing({"response": data}, slug):
                    if product.product_ref not in refs:
                        refs.add(product.product_ref)
                        products.append(product)
                crawl.page_read(len(products) - before)
                if not data.get("docs") or len(products) >= crawl.max_products(self.key):
                    break
        except ShopError as exc:
            if not products:
                raise
            raise crawl.Partial(products, exc) from exc
        return products

    def detail(self, store_data: dict) -> ShopDetail | None:
        handle = str(store_data.get("handle") or "")
        if not re.fullmatch(r"[A-Za-z0-9-]+", handle):
            return None
        if not browser.active():  # una petición HTTP normal (elegir otro color): aquí no se abre
            raise NeedsBrowser(f"{self.name} solo se lee con navegador, en las consultas en segundo plano")
        status, page = browser.require(self.key).page_html(self.key, f"{BASE}/products/{handle}")
        if status in (404, 410) or page is None:
            return None
        if status != 200:
            raise ShopError(f"HTTP {status}")
        return parse_product_page(page, store_data)

    def reference(self, store_data: dict) -> str | None:
        return reference(store_data)

    def maker_code(self, store_data: dict) -> str | None:
        return str(store_data.get("mpn") or "") or None

    def search(self, query: str, limit: int = 12) -> list[ShopProduct]:
        parse_query(query)  # NotThisStore si no es un enlace de size?; SearchError si no es de un producto
        raise SearchError(
            f"{self.name} solo se lee con navegador en las consultas semanales: el buscador no la abre. "
            "Actívala en Tiendas y saldrá en Descubrir si está en sus secciones."
        )

    def download(self, url: str) -> bytes:
        page = self.fetcher.get(url, accept=IMAGE)
        if page.status != 200 or not page.content:
            raise ShopError(f"HTTP {page.status} al bajar la foto")
        return page.content
