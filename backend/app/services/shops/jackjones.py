"""Conector de Jack & Jones (jackjones.com/fr-fr): ropa y zapatillas de hombre.

Sin navegador (investigado el 18-11-2026: httpx con cabeceras normales, ~15 peticiones sin bloqueo ni
desafío). Si un día deja de responder a un cliente normal, basta con `needs_browser = True`: las páginas
se leen igual, abiertas en el navegador (ver fetch.read_html).

- Listado: el HTML del servidor lleva `window.__INITIAL_STATE__ = {...}`; dentro, la clave
  `$getProducts-fr-fr-<hash>` (el hash cambia: se busca por el principio) con `results` (60 por página),
  `startingFrom` y `totalResults`. Las páginas siguientes, `?page=N`, como en la web. Un producto es un
  modelo en un color (`id` «12308540_2036» = estilo_color).
- El nombre de la tienda es genérico («T-shirt», «Parka»): se completa con lo que dice su enlace
  («t-shirts-standard-fit-col-rond» -> «T-shirt standard fit col rond»). El tipo sale además de su
  subcategoría (`ediSubCategory`: «Chinos», «Short en jean»…).
- Ficha: la página del producto, mismo `__INITIAL_STATE__` (`$initialContentResponse-…` -> `product`):
  tallas con stock (`variants`), composición, el tono (`pantoneHexCode`) y los otros colores con su
  enlace (`styleOptions`).
- Fotos: `001` delante y `002` detrás, sin modelo (PNG transparente: se piden a su CDN en JPG de 1280 px
  con fondo blanco). Las de modelo están marcadas `aiGenerated` (son de IA): solo si no hay otra.
- Referencia: el número de estilo («Art. n°» en la web, «12308540»).
- Buscador: `/fr-fr/search?q=` (referencia o texto) y enlaces de producto.
"""
import json
import re
from urllib.parse import quote, urlsplit

from ... import catalog, config
from . import crawl
from .base import NotThisStore, SearchError, ShopDetail, ShopError, ShopProduct
from .estimate import brand_name, estimate_color, estimate_pattern, estimate_season, estimate_style
from .estimate import estimate_type, norm, sentence_case
from .fetch import IMAGE, Fetcher, read_html

BASE = "https://www.jackjones.com"
PATH = "/fr-fr"
PAGE_SIZE = 60
MAX_PHOTOS = 3
PHOTO = "format=jpg&width=1280&quality=85&bg-color=%23ffffff"  # PNG de 15-20 MB -> JPG de ~160 KB
SEARCH_RESULTS = 6
OWN_BRANDS = {"jack & jones", "jack&jones", "jack and jones"}
# slug -> (nombre para el usuario, ruta, tipo por defecto)
CATEGORIES = {
    "t-shirts": ("Camisetas", "/t-shirts", "camiseta"),
    "polos": ("Polos", "/t-shirts/polos", "polo"),
    "chemises": ("Camisas", "/chemises", "camisa"),
    "sweat-shirts": ("Sudaderas", "/sweat-shirts", "sudadera"),
    "tricot": ("Punto", "/tricot", "jersey"),
    "manteaux-et-blousons": ("Chaquetas y abrigos", "/manteaux-et-blousons", "chaqueta"),
    "pantalons": ("Pantalones", "/pantalons", "pantalón"),
    "jeans": ("Vaqueros", "/jeans", "vaquero"),
    "shorts": ("Bermudas", "/shorts", "pantalón corto"),
    "baskets": ("Zapatillas", "/chaussures/baskets", "zapatillas"),
}
# Los polos ya están dentro de Camisetas: con Camisetas activa y leída entera, no se recorren aparte.
COVERED_BY = {"polos": ("t-shirts",)}

_STATE = re.compile(r"window\.__INITIAL_STATE__\s*=\s*")
_LINK_TEXT = re.compile(r"(?:https?://|www\.)\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}/\S*", re.IGNORECASE)
_PRODUCT_PATH = re.compile(r"/product/(\d{6,10}_[0-9A-Za-z]+)(?:/([^/?#]+))?")
_STYLE = re.compile(r"\d{8}")


def initial_state(page: str) -> dict:
    """El `window.__INITIAL_STATE__` del HTML."""
    match = _STATE.search(page or "")
    if not match:
        raise ShopError("la respuesta no era la esperada (sin datos de la página)")
    try:
        data, _end = json.JSONDecoder().raw_decode(page, match.end())
    except ValueError as exc:
        raise ShopError("la respuesta no era la esperada (datos ilegibles)") from exc
    return data if isinstance(data, dict) else {}


def _by_prefix(state: dict, prefix: str) -> dict | None:
    return next((value for key, value in state.items() if key.startswith(prefix) and isinstance(value, dict)), None)


def listing(state: dict) -> dict:
    """{"results": [...], "startingFrom", "totalResults"} del listado (o del buscador)."""
    found = _by_prefix(state, "$getProducts")
    if found is None or not isinstance(found.get("results"), list):
        raise ShopError("la respuesta no era la esperada (sin listado)")
    return found


def product_of(state: dict) -> dict | None:
    """La ficha (`product`) de la página de un producto; None si la página no es una ficha."""
    found = _by_prefix(state, "$initialContentResponse")
    product = (found or {}).get("product")
    return product if isinstance(product, dict) and product.get("id") else None


def _price(entry: dict) -> int | None:
    amount = (((entry.get("price") or {}).get("salesPrice") or {}).get("amount"))
    try:
        cents = round(float(amount) * 100)
    except (TypeError, ValueError):
        return None
    return cents if cents > 0 else None


# Las palabras con las que empiezan sus enlaces y solo dicen la clase de prenda («sweat-shirts-…»).
_CLASS_WORDS = {
    "t", "shirt", "shirts", "tee", "sweat", "sweats", "polo", "polos", "chemise", "chemises", "pull", "pulls",
    "cardigan", "cardigans", "gilet", "gilets", "jean", "jeans", "pantalon", "pantalons", "short", "shorts",
    "bermuda", "bermudas", "veste", "vestes", "blouson", "blousons", "manteau", "manteaux", "parka", "parkas",
    "doudoune", "doudounes", "chino", "chinos", "jogger", "joggers", "basket", "baskets", "chaussures",
    "surchemise", "surchemises",
}


def full_name(name: str, url: str) -> str:
    """«Sweat-shirt Uni» + «/fr-fr/product/12249341_2161/sweat-shirt-relaxed-fit-col-ras-du-cou» ->
    «Sweat-shirt Uni relaxed fit col ras du cou»: el nombre de la tienda es genérico y su enlace dice el
    corte y el cuello. Del enlace se quitan la clase de prenda del principio y lo que el nombre ya dice."""
    name = " ".join((name or "").split())
    slug = (url or "").rstrip("/").rsplit("/", 1)[-1]
    words = [w for w in slug.split("-") if w] if not re.fullmatch(r"\d+_\w+", slug) else []
    while words and norm(words[0]) in _CLASS_WORDS:
        words.pop(0)
    said = set(re.findall(r"[a-z0-9]+", norm(name)))
    words = [w for w in words if norm(w) not in said]
    text = f"{name} {' '.join(words)}".strip()
    return sentence_case(text) if not any(ch.islower() for ch in text) else text[:1].upper() + text[1:]


_SIZE_ORDER = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL", "4XL", "5XL"]


def _size_key(name: str) -> tuple:
    """Las tallas en su orden (la web las da desordenadas): XS, S, M… y las de número de menor a mayor."""
    upper = name.upper()
    if upper in _SIZE_ORDER:
        return (0, _SIZE_ORDER.index(upper), "")
    number = re.match(r"\d+(?:[.,]\d+)?", name)
    return (1, float(number.group().replace(",", ".")), name) if number else (2, 0, name)


def make_product(entry: dict, section: str) -> ShopProduct | None:
    """Un producto del listado (o de una ficha, que trae los mismos campos). None si no cabe en el armario."""
    if not isinstance(entry, dict):
        return None
    product_id = str(entry.get("id") or "")
    url = str(entry.get("url") or "")
    if not re.fullmatch(r"\d{6,10}_[0-9A-Za-z]+", product_id) or entry.get("inStock") is False:
        return None
    if str(entry.get("gender") or entry.get("englishGender") or "male").lower() not in ("male", "men", "unisex", ""):
        return None
    name = full_name(str(entry.get("name") or ""), url)
    sub = f"{entry.get('ediSubCategory') or ''} {entry.get('ediCategory') or ''}"
    default = CATEGORIES.get(section, (None, None, None))[2]
    garment_type = estimate_type(name, estimate_type(sub, default))
    price = _price(entry)
    if not name or garment_type is None or price is None:
        return None
    colour = entry.get("colour") if isinstance(entry.get("colour"), dict) else {}
    family = str(entry.get("colourFamilyName") or (colour.get("base") or {}).get("name") or "").strip()
    hex_color = colour.get("pantoneHexCode") if re.fullmatch(r"#[0-9a-fA-F]{6}", str(colour.get("pantoneHexCode") or "")) else None
    brand = str(entry.get("brand") or "")
    shown_brand = "" if norm(brand) in OWN_BRANDS or not brand else brand_name(brand)
    details = f"{name} {entry.get('ediSubCategory') or ''}".strip().lower()
    link = url if url.startswith("http") else BASE + url
    return ShopProduct(
        store="jackjones",
        product_ref=f"jackjones:{product_id}",
        name=name,
        price_cents=price,
        url=link,
        store_color=family[:60],
        section=section,
        type=garment_type,
        category=catalog.category_of(garment_type),
        color=estimate_color(family, hex_color),
        pattern=estimate_pattern(f"{name} {entry.get('styleName') or ''}"),
        style=estimate_style(name, garment_type),
        season=estimate_season(name, garment_type),
        details=details,
        brand=shown_brand,
        store_data={"id": product_id, "url": link},
    )


def parse_listing(data: dict, section: str) -> list[ShopProduct]:
    products: list[ShopProduct] = []
    refs: set[str] = set()
    for entry in data.get("results") or []:
        product = make_product(entry, section)
        if product and product.product_ref not in refs:
            refs.add(product.product_ref)
            products.append(product)
    return products


def _sizes(variants: list) -> list[dict]:
    sizes, seen = [], set()
    for variant in variants or []:
        name = str(((variant or {}).get("size") or {}).get("name") or "").strip()
        if name and name not in seen:
            seen.add(name)
            stock = variant.get("inStockEcom", variant.get("inStock"))
            sizes.append({"name": name, "in_stock": bool(stock)})
    return sorted(sizes, key=lambda size: _size_key(size["name"]))


def _sized(url: str) -> str:
    return f"{url}{'&' if '?' in url else '?'}{PHOTO}"


def _ficha_photos(product: dict) -> tuple[list[str], bool]:
    """Delante y detrás sin modelo (001, 002) y, si las hay, un detalle sin modelo; si no hay ninguna sin
    modelo, la primera (y True)."""
    media = [m for m in product.get("media") or [] if isinstance(m, dict)]
    by_id = {str(m.get("id")): m for m in media}
    photos = []
    for index in ("001", "002"):
        item = by_id.get(index)
        if item and not item.get("aiGenerated") and str(item.get("imageUrl") or "").startswith("https://"):
            photos.append(_sized(str(item["imageUrl"])))
    if photos:
        return photos[:MAX_PHOTOS], False
    first = next((m for m in media if str(m.get("imageUrl") or "").startswith("https://")), None)
    return ([_sized(str(first["imageUrl"]))] if first else []), bool(first)


def _sibling(entry: dict) -> dict | None:
    product_id = str(entry.get("id") or "")
    if not product_id:
        return None
    colour = entry.get("colour") or {}
    url = str(entry.get("url") or "")
    url = url if url.startswith("http") else BASE + url
    hex_color = colour.get("pantoneHexCode") or colour.get("hexCode")
    return {
        "product_ref": f"jackjones:{product_id}",
        "name": str((colour.get("nuance") or {}).get("name") or (colour.get("base") or {}).get("name") or ""),
        "hex": hex_color if re.fullmatch(r"#[0-9a-fA-F]{6}", str(hex_color or "")) else None,
        "url": url,
        "store_data": {"id": product_id, "url": url},
    }


def parse_product(product: dict) -> ShopDetail:
    """De la ficha (`product`) a su detalle."""
    colour = product.get("colour") or {}
    photos, model = _ficha_photos(product)
    siblings = [s for s in (_sibling(e) for e in [product, *(product.get("styleOptions") or [])]
                            if isinstance(e, dict)) if s]
    unique = list({s["product_ref"]: s for s in siblings}.values())
    hex_color = colour.get("pantoneHexCode")
    return ShopDetail(
        price_cents=_price(product),
        sizes=_sizes(product.get("variants") or []),
        photo_urls=photos,
        description=" ".join(str(product.get("description") or "").split())[:400],
        color_hex=hex_color if re.fullmatch(r"#[0-9a-fA-F]{6}", str(hex_color or "")) else None,
        composition=" ".join(str(product.get("fabricComposition") or "").split())[:300],
        siblings=sorted(unique, key=lambda s: s["product_ref"]) if len(unique) > 1 else [],
        store_color=str((colour.get("nuance") or {}).get("name") or "")[:60],
        store_data={
            **({"style": str(product["styleNumber"])} if product.get("styleNumber") else {}),
            **({"model_photo": True} if model else {}),
        },
    )


def reference(store_data: dict) -> str | None:
    """El número de estilo («12308540»), el «Art. n°» de la web."""
    style = str(store_data.get("style") or "") or str(store_data.get("id") or "").split("_")[0]
    return style if _STYLE.fullmatch(style) else (style or None)


def parse_query(text: str) -> tuple[str, str]:
    """("link", ruta del producto), ("ref", número de estilo) o ("text", texto). Lanza NotThisStore si es un
    enlace de otra tienda."""
    text = " ".join((text or "").split())
    link = _LINK_TEXT.search(text)
    if link:
        url = link.group().rstrip(".,;)")
        parts = urlsplit(url if "://" in url else f"https://{url}")
        host = (parts.hostname or "").lower()
        if host != "jackjones.com" and not host.endswith(".jackjones.com"):
            raise NotThisStore("Todavía no sé buscar en esa tienda")
        if not _PRODUCT_PATH.search(parts.path):
            raise SearchError("Ese enlace de Jack & Jones no es el de un producto: pega el de la página de la prenda")
        return "link", parts.path
    # Solo la referencia con su color, como va en sus enlaces («12308540_2036»). Ni el número de estilo a
    # secas ni el texto libre: el buscador pregunta a todas las tiendas, y una referencia de Zara de ocho
    # cifras («03918300») o cualquier texto acabarían también en Jack & Jones.
    code = re.sub(r"\b(ref|r[ée]f[ée]rence|art\.?\s*n[°o]?)\b\.?:?", " ", text, flags=re.IGNORECASE).replace(" ", "")
    if re.fullmatch(r"\d{8}_[0-9A-Za-z]{1,6}", code):
        return "ref", code
    raise NotThisStore("Jack & Jones solo busca por enlace de producto o por su referencia con el color")


class JackJonesConnector:
    key = "jackjones"
    name = "Jack & Jones"
    needs_browser = False  # True si deja de responder a un cliente normal: ver fetch.read_html
    heavy = False
    # No se sabe qué día saca novedades: los lunes (reparto de noches, ver shops/__init__.py).
    refresh_weekday = 0
    refresh_after_release = False
    language = "fr"
    categories = {slug: label for slug, (label, _path, _type) in CATEGORIES.items()}
    section_types = {slug: garment_type for slug, (_label, _path, garment_type) in CATEGORIES.items()}
    covered_by = COVERED_BY

    def __init__(self, pause: float | None = None):
        self.fetcher = Fetcher("jackjones", pause=max(config.SHOP_PAUSE_SECONDS, 3.0) if pause is None else pause,
                               timeout=config.SHOP_TIMEOUT_SECONDS, accept_language="fr-FR,fr;q=0.9")

    def _state(self, url: str) -> dict | None:
        status, text = read_html(self, url)
        if status in (404, 410):
            return None
        if status != 200:
            raise ShopError(f"HTTP {status}")
        return initial_state(text)

    def list_category(self, slug: str) -> list[ShopProduct]:
        """La sección entera, de 60 en 60 (`?page=N`), hasta la última página (o el tope)."""
        _label, path, _type = CATEGORIES[slug]
        products: list[ShopProduct] = []
        refs: set[str] = set()
        pages = None
        try:
            for number in range(1, max(1, crawl.max_pages(self.key)) + 1):
                if pages is not None and number > pages:
                    break
                crawl.before_page()
                state = self._state(f"{BASE}{PATH}{path}" + (f"?page={number}" if number > 1 else ""))
                if state is None:
                    raise ShopError("HTTP 404")
                data = listing(state)
                if pages is None:
                    total = data.get("totalResults")
                    pages = -(-int(total) // PAGE_SIZE) if isinstance(total, int) and total >= 0 else None
                    crawl.section_total(min(pages, crawl.max_pages(self.key)) if pages else None)
                before = len(products)
                for product in parse_listing(data, slug):
                    if product.product_ref not in refs:
                        refs.add(product.product_ref)
                        products.append(product)
                crawl.page_read(len(products) - before)
                if not data.get("results") or len(products) >= crawl.max_products(self.key):
                    break
        except ShopError as exc:
            if not products:
                raise
            raise crawl.Partial(products, exc) from exc
        return products

    def detail(self, store_data: dict) -> ShopDetail | None:
        url = str(store_data.get("url") or "")
        if not url.startswith(BASE + "/"):
            return None
        state = self._state(url)
        product = product_of(state) if state else None
        return parse_product(product) if product else None

    def reference(self, store_data: dict) -> str | None:
        return reference(store_data)

    def search(self, query: str, limit: int = 12) -> list[ShopProduct]:
        kind, value = parse_query(query)
        if kind == "link":
            state = self._state(BASE + value)
            product = product_of(state) if state else None
            found = make_product(product, "") if product else None
            if found is None:
                raise SearchError("No he encontrado esa prenda en Jack & Jones")
            return [found]
        # La referencia con su color: el buscador de la web (con el número de estilo trae todos sus colores).
        state = self._state(f"{BASE}{PATH}/search?q={quote(value.split('_')[0])}")
        products = parse_listing(listing(state), "") if state else []
        products = sorted((p for p in products if p.store_data["id"].startswith(value.split("_")[0] + "_")),
                          key=lambda p: p.store_data["id"] != value)  # el color pedido, el primero
        if not products:
            raise SearchError(f"No he encontrado nada en Jack & Jones con «{value}»")
        return products[: min(limit, SEARCH_RESULTS)]

    def download(self, url: str) -> bytes:
        page = self.fetcher.get(url, accept=IMAGE, pause=0.5)
        if page.status != 200 or not page.content:
            raise ShopError(f"HTTP {page.status} al bajar la foto")
        return page.content
