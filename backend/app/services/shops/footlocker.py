"""Conector de Foot Locker (footlocker.fr): SOLO zapatillas de hombre, de muchas marcas.

SIN NAVEGADOR (investigado el 18-11-2026): el servidor pinta el HTML con los datos dentro
(`window.__staticRouterHydrationData = JSON.parse("…")`) y a un cliente normal le responde 200. Con un
navegador automatizado, en cambio, su antibots (Kasada) niega todas las llamadas de la web a su API: el
conector solo lee ese HTML y NUNCA llama a `/zgw/` ni a nada protegido.

- Listado: la ruta del buscador (`/fr/search?query=:newArrivals:collection_id:men-shoes`) pinta 48
  productos, de lo más nuevo a lo más viejo. La paginación NO es fiable (la caché de su CDN guarda por
  `query` e ignora `currentPage`), así que no se pagina: se recorre por FACETAS, cada una con su primera
  página (las 48 más nuevas): todo el calzado, «Nouveautés» y cada marca y estilo que la propia página
  ofrece en sus filtros. Se junta sin repetir. Es el catálogo nuevo, no entero: las facetas grandes
  (adidas, Nike) solo dan sus 48 más nuevas.
- Ficha: la página del producto, con el mismo JSON: el código de fabricante (`supplierSkus`), las tallas
  con su stock, el color en francés y los otros colores (`styleVariants`, uno por color y talla).
- Fotos de Scene7, todas sin persona en el calzado: 01 lateral, 02 tres cuartos, 03 tres cuartos
  trasera, 05 cenital (la 06 es la suela). Llegan con el fondo transparente (aunque se pidan en JPG, su
  CDN responde WebP con transparencia): se ponen sobre blanco al bajarlas, o el fondo saldría negro.
- Buscador: por enlace, por número de Foot Locker (12 cifras) o por código de fabricante (su propio
  buscador, la misma ruta que el listado).
"""
import html
import io
import json
import re
from urllib.parse import quote, urlsplit

from ... import config
from . import crawl
from .base import NotThisStore, SearchError, ShopDetail, ShopError, ShopProduct, maker_key
from .estimate import brand_name, estimate_color, estimate_pattern, estimate_season, estimate_shoe_type
from .estimate import estimate_style, title_case
from .fetch import IMAGE, Fetcher

BASE = "https://www.footlocker.fr"
IMAGES = "https://images.footlocker.com/is/image/FLEU"
PHOTO = "wid=1600&fmt=jpg&bgc=255,255,255&qlt=85"
COLLECTION = "men-shoes"
# slug -> (nombre para el usuario, colección de Foot Locker)
CATEGORIES = {
    "chaussures": ("Zapatillas", COLLECTION),
}
# Las facetas que se recorren: marcas, estilos y «Nouveautés». No las de precio, talla, color, rebajas… ni
# la de tipo de producto (en el calzado, «Chaussures» es todo: daba otra vez los mismos 48).
_FACETS = (":brand:", ":style:", ":newArrival:", ":sport:")
MAX_PHOTOS = 4
PHOTO_ORDER = ("01", "02", "03", "05")
SEARCH_RESULTS = 6

_HYDRATION = re.compile(r"window\.__staticRouterHydrationData\s*=\s*JSON\.parse\(")
_NOT_SHOES = re.compile(r"sandale|claquette|\btongs?\b|\bmules?\b|\bslides?\b|chausson|chaussette|\bsocks?\b|"
                        r"\bslippers?\b", re.IGNORECASE)
_NOT_MEN = re.compile(r"\b(femme|femmes|enfant|enfants|b[ée]b[ée]|junior|gar[çc]on|fille)\b", re.IGNORECASE)
_SKU = re.compile(r"\d{12}")
_SKU_IN_PATH = re.compile(r"/(\d{12})\.html")
_LINK_TEXT = re.compile(r"(?:https?://|www\.)\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}/\S*", re.IGNORECASE)
_MODEL_CODE = re.compile(r"(?=[A-Z0-9-]*\d)(?=[A-Z0-9-]*[A-Z])[A-Z0-9]{4,12}(?:-[A-Z0-9]{2,4})?")
_DECODER = json.JSONDecoder()


def hydration(page: str) -> dict:
    """Los datos que el servidor mete en la página (`loaderData`)."""
    match = _HYDRATION.search(page or "")
    if not match:
        raise ShopError("la respuesta no era la esperada (sin datos de la página)")
    try:
        literal, _end = _DECODER.raw_decode(page, match.end())
        data = json.loads(literal) if isinstance(literal, str) else literal
    except ValueError as exc:
        raise ShopError("la respuesta no era la esperada (datos ilegibles)") from exc
    loader = data.get("loaderData") if isinstance(data, dict) else None
    return loader if isinstance(loader, dict) else {}


def block(loader: dict, key: str) -> dict | None:
    """El bloque de `loaderData` que trae `key` («products» en un listado, «product» en una ficha)."""
    return next((v for v in (loader or {}).values() if isinstance(v, dict) and key in v), None)


def search_url(query: str) -> str:
    return f"{BASE}/fr/search?query={quote(query, safe=':')}"


def product_url(sku: str) -> str:
    return f"{BASE}/fr/product/~/{sku}.html"


def _cents(value) -> int | None:
    try:
        cents = round(float(value) * 100)
    except (TypeError, ValueError):
        return None
    return cents if cents > 0 else None


def brands_of(listing: dict) -> list[str]:
    """Las marcas que ofrece el filtro del listado, de la más larga a la más corta (para reconocerlas
    al principio del nombre: «New Balance» antes que «New»)."""
    names = []
    for facet in (listing or {}).get("facets") or []:
        for value in (facet or {}).get("values") or []:
            query = _query_of(value)
            if ":brand:" in query and value.get("name"):
                names.append(" ".join(str(value["name"]).split()))
    return sorted(set(names), key=len, reverse=True)


def split_name(full: str, brands: list[str] = ()) -> tuple[str, str, str]:
    """«Nike Air Max Tuned 1 - Homme Chaussures» -> («Nike», «Air Max Tuned 1», «Homme Chaussures»)."""
    full = " ".join(html.unescape(full or "").split())
    model, _sep, tail = full.partition(" - ")
    low = model.lower()
    brand = next((b for b in brands if low.startswith(b.lower() + " ")), "")
    if not brand:
        for known in ("New Balance", "Under Armour", "The North Face", "Le Coq Sportif", "Dr. Martens", "Air Jordan"):
            if low.startswith(known.lower() + " "):
                brand = known
                break
    if not brand and " " in model:
        brand = model.split(" ", 1)[0]
    name = model[len(brand) + 1:] if brand and low.startswith(brand.lower() + " ") else model
    name = name if any(ch.islower() for ch in name) else title_case(name)  # «GEL-STRATUS MC» -> «Gel-Stratus MC»
    if brand == "Air Jordan":
        brand, name = "Jordan", model
    return brand_name(brand), name, tail


def _colour(style: str) -> str:
    """«Black-Hyper Pink-Black» -> «Black/Hyper Pink/Black»: el primero es el principal."""
    style = " ".join(str(style or "").split())
    return re.sub(r"(?<!off)-(?!white)", "/", style, flags=re.IGNORECASE)


def first_color(style: str) -> str:
    """Nuestro color para el de la marca: el de su primer tramo y, dentro de él, la primera palabra que
    dice un color («White Black-…» es blanco; «Light Smoke Grey», gris; «Off White», crudo)."""
    first = _colour(style).split("/")[0]
    words = first.split(" ")
    for size in range(1, len(words) + 1):
        found = estimate_color(" ".join(words[:size]))
        if found:
            return found
    return estimate_color(_colour(style))


def make_product(item: dict, section: str, brands: list[str] = ()) -> ShopProduct | None:
    """Un producto del listado. None si no es calzado de hombre del armario."""
    if not isinstance(item, dict):
        return None
    sku = str(item.get("sku") or "")
    brand, name, tail = split_name(str(item.get("name") or ""), brands)
    price = _cents((item.get("price") or {}).get("value"))
    options = item.get("baseOptions") or [{}]
    style = str(((options[0] or {}).get("selected") or {}).get("style") or "") if isinstance(options[0], dict) else ""
    if not _SKU.fullmatch(sku) or not name or price is None or _NOT_SHOES.search(f"{name} {tail}") or _NOT_MEN.search(tail):
        return None
    shoe_type = estimate_shoe_type(f"{name} {tail}")
    if shoe_type is None:
        return None
    return ShopProduct(
        store="footlocker",
        product_ref=f"footlocker:{sku}",
        name=name,
        price_cents=price,
        url=product_url(sku),
        store_color=style[:60],
        section=section,
        type=shoe_type,
        category="calzado",
        color=first_color(style),
        pattern=estimate_pattern(name),
        style=estimate_style(f"{name} {tail}", shoe_type),
        season=estimate_season(name, shoe_type),
        details=f"{brand} {name}".strip().lower(),
        brand=brand,
        store_data={"sku": sku, "new": bool(item.get("isNewProduct"))},
    )


def parse_listing(listing: dict, section: str) -> list[ShopProduct]:
    brands = brands_of(listing)
    products: list[ShopProduct] = []
    refs: set[str] = set()
    for item in (listing or {}).get("products") or []:
        product = make_product(item, section, brands)
        if product and product.product_ref not in refs:
            refs.add(product.product_ref)
            products.append(product)
    return products


def _query_of(value: dict) -> str:
    query = (value or {}).get("query")
    if isinstance(query, dict):
        inner = query.get("query")
        return str(inner.get("value") if isinstance(inner, dict) else query.get("value") or "")
    return str(query or "")


def facet_queries(listing: dict) -> list[str]:
    """Las facetas de marca, estilo y novedad que ofrece el listado, como consultas ordenadas por novedad,
    de la que más productos tiene a la que menos."""
    found: dict[str, int] = {}
    for facet in (listing or {}).get("facets") or []:
        for value in (facet or {}).get("values") or []:
            query = _query_of(value)
            if not query.startswith(":") or not any(mark in query for mark in _FACETS):
                continue
            if ":newArrival:" in query and not query.endswith(":True"):
                continue
            parts = query.split(":")
            parts[1] = "newArrivals"  # la primera es el orden: lo más nuevo primero
            count = value.get("count") if isinstance(value.get("count"), int) else 0
            if count > 0:
                found[":".join(parts)] = count
    return [query for query, _count in sorted(found.items(), key=lambda pair: (-pair[1], pair[0]))]


def parse_product(product_block: dict) -> tuple[dict, ShopDetail] | None:
    """De la ficha (el bloque con `product` y `gallery`) a (datos del producto, detalle)."""
    product = (product_block or {}).get("product")
    if not isinstance(product, dict) or not isinstance(product.get("style"), dict):
        return None
    model, style = product.get("model") or {}, product["style"]
    sku = str(style.get("sku") or "")
    if not _SKU.fullmatch(sku):
        return None
    sizes, seen = [], set()
    for size in product.get("sizes") or []:
        name = str((size or {}).get("size") or ((size or {}).get("sizeVariants") or {}).get("eu") or "").strip()
        if name and name not in seen:
            seen.add(name)
            sizes.append({"name": name, "in_stock": bool(((size or {}).get("inventory") or {}).get("inventoryAvailable"))})
    by_sku: dict[str, dict] = {}
    for variant in product.get("styleVariants") or []:
        other = str((variant or {}).get("sku") or "")
        if not _SKU.fullmatch(other):
            continue
        entry = by_sku.setdefault(other, {"color": str(variant.get("color") or ""), "price": None, "stock": False})
        entry["price"] = entry["price"] or _cents(((variant.get("price") or {}).get("salePrice")))
        entry["stock"] = entry["stock"] or bool((variant.get("inventory") or {}).get("inventoryAvailable"))
    siblings = [
        {"product_ref": f"footlocker:{other}", "name": info["color"], "hex": None, "price_cents": info["price"],
         "url": product_url(other), "store_data": {"sku": other}}
        for other, info in by_sku.items()
        if info["stock"] or other == sku
    ]
    if siblings and not any(s["product_ref"] == f"footlocker:{sku}" for s in siblings):
        siblings.append({"product_ref": f"footlocker:{sku}", "name": str(style.get("color") or ""), "hex": None,
                         "url": product_url(sku), "store_data": {"sku": sku}})
    views: dict[str, str] = {}
    for item in (((product_block.get("gallery") or {}).get("set") or {}).get("items") or []):
        name = str(((item or {}).get("i") or {}).get("n") or "").rsplit("/", 1)[-1]
        match = re.fullmatch(rf"{sku}_(\d\d)", name)
        if match:
            views.setdefault(match.group(1), name)
    if not views:  # sin galería: las de siempre, por si están
        views = {"01": f"{sku}_01"}
    photos = [f"{IMAGES}/{views[v]}?{PHOTO}" for v in PHOTO_ORDER if v in views] if "01" in views else []
    supplier = [str(code) for code in (style.get("vendorAttributes") or {}).get("supplierSkus") or [] if maker_key(code)]
    price = style.get("price") or {}
    description = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", str(model.get("description") or ""))).split())
    description = re.sub(r"^Mention relative au contenu assisté par l'IA\..*?(?=Description du produit|$)", "",
                         description).replace("Description du produit", "").strip()
    materials = [k for k in style.get("keywords") or [] if isinstance(k, str) and k.lower() in (
        "maille", "synthétique", "cuir", "daim", "textile", "toile", "nubuck", "caoutchouc", "mesh")]
    info = {
        "sku": sku, "name": str(model.get("name") or ""), "brand": str(model.get("brand") or ""),
        "style": str(style.get("color") or ""), "price": _cents(price.get("salePrice")),
    }
    detail = ShopDetail(
        price_cents=_cents(price.get("salePrice")),
        sizes=sizes,
        photo_urls=photos[:MAX_PHOTOS],
        description=description[:400],
        composition=", ".join(dict.fromkeys(m.lower() for m in materials)),
        siblings=sorted(siblings, key=lambda s: s["product_ref"]) if len(siblings) > 1 else [],
        store_color=" ".join(str(style.get("primaryColor") or "").split()),
        store_data={"mpn": supplier[0]} if supplier else {},
    )
    return info, detail


def reference(store_data: dict) -> str | None:
    """El código de fabricante («DM0032-020») si ya se leyó la ficha; si no, el número de Foot Locker."""
    return str(store_data.get("mpn") or store_data.get("sku") or "") or None


def parse_query(text: str) -> tuple[str, str]:
    """Lo que se busca: ("sku", número de Foot Locker) de un enlace o del número a secas, o ("code",
    código de fabricante). Lanza NotThisStore con lo demás (texto libre, enlaces de otras tiendas)."""
    text = " ".join((text or "").split())
    link = _LINK_TEXT.search(text)
    if link:
        url = link.group().rstrip(".,;)")
        parts = urlsplit(url if "://" in url else f"https://{url}")
        host = (parts.hostname or "").lower()
        if not re.fullmatch(r"(?:[a-z0-9-]+\.)*footlocker\.[a-z.]{2,6}", host):
            raise NotThisStore("Todavía no sé buscar en esa tienda")
        match = _SKU_IN_PATH.search(parts.path)
        if not match:
            raise SearchError("Ese enlace de Foot Locker no es el de un producto: pega el de la página de la zapatilla")
        return "sku", match.group(1)
    bare = re.sub(r"(?<!\w)(ref|r[ée]f(?:[ée]rence)?|code|mod[eè]le|style|article)(?!\w)\.?:?", " ", text,
                  flags=re.IGNORECASE).strip()
    if _SKU.fullmatch(bare):
        return "sku", bare
    code = bare.upper().replace(" ", "")
    if _MODEL_CODE.fullmatch(code):
        return "code", code
    raise NotThisStore("Foot Locker solo busca por enlace o por código de fabricante")


class FootLockerConnector:
    key = "footlocker"
    name = "Foot Locker"
    needs_browser = False  # con navegador, su antibots niega la API de la web: solo el HTML, sin navegador
    heavy = False
    # No se sabe qué día saca novedades: los viernes (reparto de noches, ver shops/__init__.py).
    refresh_weekday = 4
    refresh_after_release = False
    language = "fr"
    categories = {slug: label for slug, (label, _collection) in CATEGORIES.items()}
    section_types = {slug: "zapatillas" for slug in CATEGORIES}

    def __init__(self, pause: float | None = None):
        self.fetcher = Fetcher("footlocker", pause=max(config.SHOP_PAUSE_SECONDS, 3.0) if pause is None else pause,
                               timeout=config.SHOP_TIMEOUT_SECONDS, accept_language="fr-FR,fr;q=0.9")

    def _loader(self, url: str) -> dict | None:
        page = self.fetcher.get(url)
        if page.status in (404, 410):
            return None
        if page.status != 200:
            raise ShopError(f"HTTP {page.status}")
        return hydration(page.text)

    def _listing(self, query: str) -> dict:
        loader = self._loader(search_url(query))
        listing = block(loader or {}, "products")
        if listing is None:
            raise ShopError("la respuesta no era la esperada (sin listado)")
        return listing

    def list_category(self, slug: str) -> list[ShopProduct]:
        """Lo nuevo de la sección por facetas: la primera página de todo el calzado y después la de cada
        marca, estilo y «Nouveautés» que ofrece su filtro (48 cada una). Si una falla a mitad,
        `crawl.Partial` con lo leído."""
        _label, collection = CATEGORIES[slug]
        products: list[ShopProduct] = []
        refs: set[str] = set()
        brands: list[str] = []

        def add(listing: dict) -> int:
            before = len(products)
            for item in listing.get("products") or []:
                product = make_product(item, slug, brands)
                if product and product.product_ref not in refs:
                    refs.add(product.product_ref)
                    products.append(product)
            return len(products) - before

        crawl.before_page()
        first = self._listing(f":newArrivals:collection_id:{collection}")
        brands = brands_of(first)
        facets = facet_queries(first)[: max(0, crawl.max_pages(self.key) - 1)]
        crawl.section_total(1 + len(facets))
        crawl.page_read(add(first))
        try:
            for query in facets:
                if len(products) >= crawl.max_products(self.key):
                    break
                crawl.before_page()
                crawl.page_read(add(self._listing(query)))
        except ShopError as exc:
            raise crawl.Partial(products, exc) from exc
        return products

    def _product(self, sku: str) -> tuple[dict, ShopDetail] | None:
        loader = self._loader(product_url(sku))
        found = block(loader or {}, "product")
        return parse_product(found) if found else None

    def detail(self, store_data: dict) -> ShopDetail | None:
        sku = str(store_data.get("sku") or "")
        if not _SKU.fullmatch(sku):
            return None
        parsed = self._product(sku)
        return parsed[1] if parsed else None

    def reference(self, store_data: dict) -> str | None:
        return reference(store_data)

    def maker_code(self, store_data: dict) -> str | None:
        return str(store_data.get("mpn") or "") or None

    def search(self, query: str, limit: int = 12) -> list[ShopProduct]:
        kind, value = parse_query(query)
        if kind == "sku":
            parsed = self._product(value)
            if not parsed:
                raise SearchError("No he encontrado esa zapatilla en Foot Locker")
            info, detail = parsed
            item = {"sku": info["sku"], "name": info["name"], "price": {"value": (info["price"] or 0) / 100},
                    "baseOptions": [{"selected": {"style": info["style"]}}]}
            product = make_product(item, "", [info["brand"]] if info["brand"] else [])
            if product is None:
                raise SearchError("Eso no son unas zapatillas de hombre que quepan en el armario")
            product.store_data.update(detail.store_data)
            return [product]
        listing = self._listing(value)
        found = parse_listing(listing, "")
        # Un código de fabricante es un modelo en un color: si salen muchos, el buscador ha buscado otra cosa.
        if not found or len(listing.get("products") or []) > 3:
            raise SearchError(f"No he encontrado nada en Foot Locker con el código {value}")
        return found[: min(limit, SEARCH_RESULTS)]

    def download(self, url: str) -> bytes:
        page = self.fetcher.get(url, accept=IMAGE, pause=0.5)
        if page.status != 200 or not page.content:
            raise ShopError(f"HTTP {page.status} al bajar la foto")
        return on_white(page.content)


def on_white(content: bytes) -> bytes:
    """La foto sobre fondo blanco si trae transparencia (las de Foot Locker); si no, tal cual."""
    from PIL import Image  # aquí: solo hace falta al bajar fotos

    try:
        image = Image.open(io.BytesIO(content))
        if image.mode not in ("RGBA", "LA", "P") or (image.mode == "P" and "transparency" not in image.info):
            return content
        image = image.convert("RGBA")
        flat = Image.new("RGB", image.size, (255, 255, 255))
        flat.paste(image, mask=image.getchannel("A"))
        out = io.BytesIO()
        flat.save(out, "JPEG", quality=90)
        return out.getvalue()
    except Exception:  # una foto rara: que la guarde (o la rechace) el almacén como siempre
        return content
