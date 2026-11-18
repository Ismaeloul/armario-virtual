"""Conector de Courir (courir.com, Francia): zapatillas de hombre de muchas marcas.

Sin navegador: la web (Salesforce Commerce Cloud) pinta el HTML en el servidor.

- Listado: el fragmento que pide el botón «Afficher plus» (`Search-UpdateGrid`), de 40 en 40. Es el
  único que trae los precios (la primera página los pinta después, en el navegador). Cada producto
  lleva en `data-gtm` su marca, nombre, sku (el de Courir, uno por color) y `supplier_id` (el código
  del fabricante, tipo IF6490). No trae el color: sale en la ficha.
- Se lee cada categoría entera (ver crawl.py). Las novedades de hombre (`HOMME-NOUVEAUTES`, filtrando
  el calzado) solo se recorren si Zapatillas o Botas no están activas: si lo están, ya las contienen.
- Ficha: ld+json (nombre, precio, fotos), tallas EU en los botones, color y otros colores del modelo.
- Buscador: por enlace de producto o por código de fabricante (el de la caja y la etiqueta).
"""
import html
import json
import re
import time
from urllib.parse import quote, urlsplit

from ... import config
from . import crawl
from .base import NotThisStore, SearchError, ShopDetail, ShopError, ShopProduct, old_price
from .estimate import brand_name, estimate_color, estimate_pattern, estimate_season
from .estimate import estimate_shoe_type, estimate_style, title_case
from .fetch import IMAGE, Fetcher

# País de la tienda. Para añadir otro, una entrada en SITES.
COUNTRY = "fr"
SITES = {
    "fr": {
        "base": "https://www.courir.com",
        "path": "/fr",
        "grid": "/on/demandware.store/Sites-Courir-FR-Site/fr_FR/Search-UpdateGrid",
        "accept_language": "fr-FR,fr;q=0.9",
        "language": "fr",
    },
}
SITE = SITES[COUNTRY]
BASE = SITE["base"]

PAGE_SIZE = 40
# slug -> (nombre para el usuario, categoría de Courir). Se leen enteras, de 40 en 40.
CATEGORIES = {
    "nouveautes": ("Novedades", "HOMME-NOUVEAUTES"),
    "sneakers": ("Zapatillas", "HOMME-CHAUSSURES-SNEAKERS"),
    "boots": ("Botas", "HOMME-CHAUSSURES-BOOTS-BOTTINES"),
}
# Con el catálogo entero, las novedades de calzado ya están dentro de Zapatillas y Botas.
COVERED_BY = {"nouveautes": ("sneakers", "boots")}
MAX_PHOTOS = 4
PHOTO_SIZE = 1200
PAGE_CACHE_SECONDS = 300
SEARCH_RESULTS = 6

_TILE_SPLIT = re.compile(r'<li class="grid-tile')
_GTM = re.compile(r'data-gtm="([^"]*)"')
_HREF = re.compile(r'class="product__link__overlay"\s+href="([^"]+)"')
_FULL_PRICE = re.compile(r'js-product__default-price"[^>]*?data-value="EUR ([\d.]+)"', re.S)
_PROMO_PRICE = re.compile(r'js-product__promotional-price"[^>]*?data-value="EUR ([\d.]+)"', re.S)
_SKU_IN_URL = re.compile(r"-(\d{6,8})\.html")
# La dirección de una ficha sin su número: «nike-air-force-1-low-nubuck» (marca, modelo y acabado).
_MODEL_IN_URL = re.compile(r"/p/([^/?#]+)-\d{6,8}\.html")
_LD_JSON = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
_SIZE = re.compile(r"Taille:\s*([^'\"]*)['\"][^>]*?data-is-available=\"(\w+)\"")
_COLOR_TEXT = re.compile(r'class="color-text">([^<]*)<')
_LINKS = re.compile(r'id="js_productlinks"(.*?)</ul>', re.S)
_LINK = re.compile(r'<a href="([^"]+)" title="([^"]*)"[^>]*?data-masterid="(\d+)"', re.S)
_PRODUCT_GTM = re.compile(r"JSON\.parse\('(\{.*?\})'\)")
_PHOTO_NUMBER = re.compile(r"_(\d)(\d\d)\.jpg")
# Un código de fabricante: letras y cifras, quizá con un guion (IF6490, DD1391-100, 1203A739-200, U9060EEE).
_MODEL_CODE = re.compile(r"(?=[A-Z0-9-]*\d)(?=[A-Z0-9-]*[A-Z])[A-Z0-9]{3,10}(?:-[A-Z0-9]{2,4})?")
_LINK_TEXT = re.compile(r"(?:https?://|www\.)\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}/\S*", re.IGNORECASE)


def _price_cents(value: str | None) -> int | None:
    try:
        cents = round(float(value) * 100)
    except (TypeError, ValueError):
        return None
    return cents if cents > 0 else None


def _clean_name(name: str, brand: str) -> str:
    """El nombre del modelo, sin la marca delante si la repite, en formato de título."""
    name = " ".join((name or "").split())
    if brand and name.lower().startswith(brand.lower() + " ") and len(name) > len(brand) + 2:
        name = name[len(brand) + 1:]
    return title_case(name)


def reference(store_data: dict) -> str | None:
    """El código del fabricante (el de la caja: «IF6490»); si no se sabe, el número de Courir."""
    return str(store_data.get("model") or store_data.get("sku") or "") or None


def model_slug(url: str | None) -> str:
    """El modelo de una ficha según su dirección, sin el número de producto. "" si no es una ficha."""
    match = _MODEL_IN_URL.search(url or "")
    return match.group(1).lower() if match else ""


def same_model(url: str | None, other_url: str | None) -> bool:
    """¿Son la misma zapatilla en otro color? El bloque «Couleur» de una ficha enlaza toda la línea
    (desde una Air Force 1 Low: la Luxe, la Mid Gore-Tex, la Low Tech, la de ante… hasta 41 productos,
    cada uno con su nombre y su precio). Solo es otro color el que comparte dirección salvo el número:
    «nike-air-force-1-low-1603614» y «nike-air-force-1-low-1227773» sí; «…-low-nubuck-1462216» no."""
    slug = model_slug(url)
    return bool(slug) and slug == model_slug(other_url)


def make_product(*, sku: str, name: str, brand: str, url: str, price_cents: int, section: str,
                 model: str | None, store_color: str = "", old_price_cents: int | None = None,
                 old_price_known: bool = False) -> ShopProduct | None:
    """Un producto de Courir normalizado. None si no es calzado del armario (chanclas, calcetines…)."""
    shown_brand = brand_name(brand)
    clean = _clean_name(name, shown_brand)
    shoe_type = estimate_shoe_type(f"{name} {section}")
    if not clean or shoe_type is None or not sku:
        return None
    text = f"{shown_brand} {clean}".strip()
    return ShopProduct(
        store="courir",
        product_ref=f"courir:{sku}",
        name=clean,
        price_cents=price_cents,
        old_price_cents=old_price(price_cents, old_price_cents),
        old_price_known=old_price_known,
        url=url,
        store_color=store_color,
        section=section,
        type=shoe_type,
        category="calzado",
        # El listado no dice el color: se adivina por el nombre («True Blue») y se corrige con la ficha.
        color=estimate_color(store_color or name),
        pattern=estimate_pattern(name),
        style=estimate_style(name, shoe_type),
        season=estimate_season(name, shoe_type),
        details=text.lower(),
        brand=shown_brand,
        store_data={"sku": sku, "url": url, "model": model or None},
    )


def parse_grid(page: str, section: str, only_shoes: bool = False) -> list[ShopProduct]:
    """Del fragmento de `Search-UpdateGrid` a productos. `only_shoes`: de las novedades, solo el calzado
    de hombre (traen también ropa y alguna cosa de mujer)."""
    products: list[ShopProduct] = []
    refs: set[str] = set()
    for chunk in _TILE_SPLIT.split(page)[1:]:
        gtm_match = _GTM.search(chunk)
        href = _HREF.search(chunk)
        if not gtm_match or not href:
            continue
        try:
            gtm = json.loads(html.unescape(gtm_match.group(1)))
        except ValueError:
            continue
        if not isinstance(gtm, dict):
            continue
        category = str(gtm.get("category") or "")
        if only_shoes and not category.startswith("HOMME-CHAUSSURES"):
            continue
        if "CLAQUETTES" in category:
            continue
        promo, full = _PROMO_PRICE.search(chunk), _FULL_PRICE.search(chunk)
        price = _price_cents(promo.group(1) if promo else None) or _price_cents(full.group(1) if full else None)
        if price is None:
            continue
        url = BASE + html.unescape(href.group(1)) if href.group(1).startswith("/") else html.unescape(href.group(1))
        product = make_product(
            sku=str(gtm.get("sku") or ""), name=str(gtm.get("name") or ""), brand=str(gtm.get("brand") or ""),
            url=url, price_cents=price, section=section, model=str(gtm.get("supplier_id") or "") or None,
            # En rebaja, la tarjeta trae el precio de siempre (`default-price`, tachado) y el rebajado
            # (`promotional-price`): visto en los listados guardados (210 € antes, 150 € ahora).
            old_price_cents=_price_cents(full.group(1) if full else None) if promo else None, old_price_known=True,
        )
        if product and product.product_ref not in refs:
            refs.add(product.product_ref)
            products.append(product)
    return products


def _ld_product(page: str) -> dict | None:
    for match in _LD_JSON.finditer(page):
        try:
            data = json.loads(match.group(1))
        except ValueError:
            continue
        for node in (data.get("@graph") if isinstance(data, dict) and "@graph" in data else [data]):
            if isinstance(node, dict) and node.get("@type") == "Product":
                return node
    return None


def _product_gtm(page: str) -> dict:
    """Los datos que la ficha da a su analítica: el código de fabricante (`supplier_id`) sale de aquí."""
    for match in _PRODUCT_GTM.finditer(page):
        try:
            data = json.loads(match.group(1).replace("\\'", "'"))
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("sku"):
            return data
    return {}


def _photos(images: list) -> list[str]:
    """Fotos de producto, en el orden de la app para calzado: lateral (1), tres cuartos (2), trasera en
    tres cuartos (4) y cenital con la suela (3). La 5.ª suele ser una foto puesta: fuera."""
    by_number: dict[int, str] = {}
    for url in images:
        if not isinstance(url, str):
            continue
        match = _PHOTO_NUMBER.search(url)
        number = int(match.group(2)) if match else 0
        if 1 <= number <= 4:
            by_number.setdefault(number, re.sub(r"sw=\d+&sh=\d+", f"sw={PHOTO_SIZE}&sh={PHOTO_SIZE}", url))
    if 1 not in by_number:
        return []
    return [by_number[n] for n in (1, 2, 4, 3) if n in by_number][:MAX_PHOTOS]


def parse_product_page(page: str) -> tuple[dict, ShopDetail] | None:
    """De la ficha a (datos del producto, detalle). None si no es una ficha de producto."""
    product = _ld_product(page)
    if not product:
        return None
    offers = product.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    gtm = _product_gtm(page)
    sizes, seen = [], set()
    for name, available in _SIZE.findall(page):
        name = html.unescape(name).strip()
        if name and name not in seen:
            seen.add(name)
            sizes.append({"name": name, "in_stock": available == "true"})
    color = _COLOR_TEXT.search(page)
    store_color = html.unescape(color.group(1)).strip() if color else ""
    siblings = []
    links = _LINKS.search(page)
    for url, title, sku in _LINK.findall(links.group(1) if links else ""):
        url = html.unescape(url)
        if url.startswith("/"):
            url = BASE + url
        name = html.unescape(title).split(":", 1)[-1].strip()
        if any(s["product_ref"] == f"courir:{sku}" for s in siblings):
            continue
        siblings.append({
            "product_ref": f"courir:{sku}", "name": name, "hex": None, "url": url,
            "store_data": {"sku": sku, "url": url, "model": None},
        })
    sku = str(product.get("sku") or gtm.get("sku") or "")
    url = str(offers.get("url") or product.get("url") or "")
    # De todo lo que enlaza la ficha, solo los colores de esta misma zapatilla (ver `same_model`).
    own = url if model_slug(url) else next((s["url"] for s in siblings if s["product_ref"] == f"courir:{sku}"), "")
    siblings = [s for s in siblings if same_model(own, s["url"])]
    info = {
        "sku": sku,
        "name": str(product.get("name") or gtm.get("name") or ""),
        "brand": str((product.get("brand") or {}).get("name") or gtm.get("brand") or ""),
        "url": url,
        "model": str(gtm.get("supplier_id") or "") or None,
        "store_color": store_color,
        "available": "InStock" in str(offers.get("availability") or ""),
    }
    images = product.get("image") or []
    detail = ShopDetail(
        price_cents=_price_cents(offers.get("price")),
        sizes=sizes,
        photo_urls=_photos(images if isinstance(images, list) else [images]),
        description=" ".join(html.unescape(str(product.get("description") or "")).split()),
        siblings=siblings if len(siblings) > 1 else [],
        store_color=store_color,
        store_data={"model": info_model} if (info_model := str(gtm.get("supplier_id") or "")) else {},
    )
    return info, detail


def parse_query(text: str) -> tuple[str, str]:
    """Lo que se busca: ("link", ruta del producto) o ("model", código de fabricante).
    Lanza NotThisStore si no es nada que Courir sepa buscar (texto libre, enlaces de otras tiendas)."""
    text = " ".join((text or "").split())
    link = _LINK_TEXT.search(text)
    if link:
        url = link.group().rstrip(".,;)")
        parts = urlsplit(url if "://" in url else f"https://{url}")
        host = (parts.hostname or "").lower()
        if host != "courir.com" and not host.endswith(".courir.com"):
            raise NotThisStore("Todavía no sé buscar en esa tienda")
        if not _SKU_IN_URL.search(parts.path):
            raise SearchError("Ese enlace de Courir no es el de un producto: pega el de la página de la zapatilla")
        return "link", parts.path
    bare = re.sub(r"\b(ref|r[ée]f[ée]rence|code|mod[eè]le|style)\b\.?:?", " ", text, flags=re.IGNORECASE).strip()
    code = bare.upper().replace(" ", "")
    if _MODEL_CODE.fullmatch(code):
        return "model", code
    raise NotThisStore("Courir solo busca por enlace o por código de fabricante")


def _same_model(code: str, model: str | None) -> bool:
    """IF6490 encuentra IF6490 e IF6490-xxx; DD1391-100 solo ese color."""
    model = (model or "").upper()
    return bool(model) and (model == code or model.split("-")[0] == code)


class CourirConnector:
    key = "courir"
    name = "Courir"
    # No se sabe qué día saca novedades: se consulta los martes.
    refresh_weekday = 1  # lunes = 0
    refresh_after_release = False
    language = SITE["language"]
    categories = {slug: label for slug, (label, _cgid) in CATEGORIES.items()}
    covered_by = COVERED_BY
    section_types = {"nouveautes": "zapatillas", "sneakers": "zapatillas", "boots": "botas"}
    heavy = False
    # Cada ficha enlaza solo a algunos de sus otros colores (la gris a cuatro, la beige solo a la gris):
    # la familia se va completando con lo que dice cada una (ver `shopping._apply_detail`).
    partial_colors = True

    def __init__(self, pause: float | None = None, timeout: float | None = None):
        self.fetcher = Fetcher(
            "courir",
            pause=max(config.SHOP_PAUSE_SECONDS, 1.5) if pause is None else pause,
            timeout=config.SHOP_TIMEOUT_SECONDS if timeout is None else timeout,
            accept_language=SITE["accept_language"],
        )
        self._pages: dict[str, tuple[float, str]] = {}  # sku -> (cuándo, ficha recién leída)

    def _get(self, url: str, accept: str | None = None, pause: float | None = None):
        if accept is None:
            return self.fetcher.get(url, pause=pause)
        return self.fetcher.get(url, accept=accept, pause=pause)

    def _grid(self, query: str, start: int) -> str:
        page = self._get(f"{BASE}{SITE['grid']}?{query}&start={start}&sz={PAGE_SIZE}")
        if page.status != 200:
            raise ShopError(f"HTTP {page.status}")
        return page.text

    def list_category(self, slug: str) -> list[ShopProduct]:
        """La categoría entera, de 40 en 40, hasta la página que trae menos (o hasta el tope)."""
        _label, cgid = CATEGORIES[slug]
        products: list[ShopProduct] = []
        refs: set[str] = set()
        try:
            for number in range(max(1, crawl.max_pages(self.key))):
                crawl.before_page()
                page = self._grid(f"cgid={cgid}", number * PAGE_SIZE)
                tiles = len(_TILE_SPLIT.findall(page))
                if number == 0 and tiles == 0 and "grid-tile" not in page:
                    raise ShopError("la respuesta no era la esperada (sin productos)")
                before = len(products)
                for product in parse_grid(page, slug, only_shoes=slug == "nouveautes"):
                    if product.product_ref not in refs:
                        refs.add(product.product_ref)
                        products.append(product)
                crawl.page_read(len(products) - before)
                if tiles < PAGE_SIZE or len(products) >= crawl.max_products(self.key):
                    break  # no hay más páginas (o el tope de seguridad)
        except ShopError as exc:
            if not products:
                raise
            raise crawl.Partial(products, exc) from exc
        return products

    def _product_page(self, url: str) -> str | None:
        sku = (_SKU_IN_URL.search(url) or [None, ""])[1]
        cached = self._pages.get(sku)
        if cached and time.monotonic() - cached[0] < PAGE_CACHE_SECONDS:
            return cached[1]
        page = self._get(url)
        if page.status in (404, 410):
            return None
        if page.status != 200:
            raise ShopError(f"HTTP {page.status}")
        now = time.monotonic()
        self._pages = {k: v for k, v in self._pages.items() if now - v[0] < PAGE_CACHE_SECONDS}
        self._pages[sku] = (now, page.text)
        return page.text

    def detail(self, store_data: dict) -> ShopDetail | None:
        url = store_data.get("url") or ""
        if not url.startswith(BASE + "/"):
            return None
        page = self._product_page(url)
        if page is None:
            return None
        parsed = parse_product_page(page)
        if parsed is None:
            # Una ficha que ya no existe redirige a una categoría o a la portada.
            return None
        return parsed[1]

    def reference(self, store_data: dict) -> str | None:
        return reference(store_data)

    def maker_code(self, store_data: dict) -> str | None:
        return str(store_data.get("model") or "") or None

    def same_model(self, url: str | None, other_url: str | None) -> bool:
        return same_model(url, other_url)

    def search(self, query: str, limit: int = 12) -> list[ShopProduct]:
        kind, value = parse_query(query)
        if kind == "link":
            page = self._product_page(BASE + value)
            parsed = parse_product_page(page) if page else None
            if not parsed:
                raise SearchError("No he encontrado esa zapatilla en Courir")
            info, detail = parsed
            product = make_product(
                sku=info["sku"], name=info["name"], brand=info["brand"], url=info["url"] or BASE + value,
                price_cents=detail.price_cents or 0, section="", model=info["model"], store_color=info["store_color"],
            )
            if product is None or not product.price_cents:
                raise SearchError("Eso no es calzado que quepa en el armario")
            return [product]
        # Por código de fabricante: el buscador de la web, con el mismo fragmento que el listado.
        page = self._grid(f"q={quote(value)}", 0)
        found = [p for p in parse_grid(page, "") if _same_model(value, p.store_data.get("model"))]
        if not found:
            raise SearchError(f"No he encontrado nada en Courir con el código {value}")
        # El buscador mezcla hombre y mujer: el mismo modelo sale dos veces, y se enseñan los dos.
        return found[: min(limit, SEARCH_RESULTS)]

    def download(self, url: str) -> bytes:
        # Las fotos piden una cabecera Accept de imagen (sin ella, 403) y la URL con su `dw…`.
        page = self._get(url, accept=IMAGE, pause=0.5)
        if page.status != 200 or not page.content:
            raise ShopError(f"HTTP {page.status} al bajar la foto")
        return page.content

