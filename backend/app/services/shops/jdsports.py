"""Conector de JD Sports (de momento jdsports.fr): zapatillas de hombre de muchas marcas.

Se lee CON PEGAS (ver la investigación del 18-11-2026):

- Los datos van en el `__NEXT_DATA__` de cada página (Next.js). El servidor solo pinta las 72 primeras
  de cada ruta, en el orden «recomendados»; la web pagina y ordena en el navegador con un servicio
  de búsqueda de terceros que aquí NO se consulta. Para cubrir más catálogo se recorren varias rutas
  (novedades, subcategorías y marcas) y se ordena en local por antigüedad (`ageDaysRound`).
- La web responde 403 a httpx (con o sin HTTP/2) en casi todo y 200 a `curl` con las mismas
  cabeceras: las páginas se piden con `curl` (fetch.py). Las fotos, de la CDN, con httpx.
- Sin buscador: el de la web va por ese servicio de terceros. Solo se busca por enlace de producto.
"""
import html
import json
import re
from urllib.parse import urlsplit

from ... import config
from .base import NotThisStore, SearchError, ShopDetail, ShopError, ShopProduct
from .estimate import brand_name, estimate_color, estimate_pattern, estimate_season, estimate_shoe_type
from .estimate import estimate_style, title_case
from .fetch import IMAGE, Fetcher

# País de la tienda: "fr" ahora; "es" es la misma web con otras rutas (comprobadas en la investigación
# solo las de zapatillas). Para cambiar de país basta esta constante.
COUNTRY = "fr"
SITES = {
    "fr": {
        "base": "https://www.jdsports.fr",
        "suffix": "_jdsportsfr",
        "accept_language": "fr-FR,fr;q=0.9",
        "language": "fr",
        "men": {"homme", "hommes", "unisexe", "mixte", "adulte"},
        # slug -> (nombre para el usuario, ruta)
        "routes": {
            "new-in": ("Novedades", "/homme/chaussures-homme/new-in/"),
            "baskets": ("Zapatillas", "/homme/chaussures-homme/baskets/"),
            "nike": ("Nike", "/homme/chaussures-homme/baskets/marque/nike/"),
            "adidas": ("Adidas", "/homme/chaussures-homme/baskets/marque/adidas/"),
            "new-balance": ("New Balance", "/homme/chaussures-homme/baskets/marque/new-balance/"),
            "running": ("Running", "/homme/chaussures-homme/chaussures-de-running/"),
            "bottes": ("Botas y zapatos", "/homme/chaussures-homme/bottes-et-chaussures/"),
        },
    },
    "es": {
        "base": "https://www.jdsports.es",
        "suffix": "_jdsportses",
        "accept_language": "es-ES,es;q=0.9",
        "language": "es",
        "men": {"hombre", "hombres", "unisex", "adulto"},
        "routes": {
            "baskets": ("Zapatillas", "/hombre/calzado-de-hombre/zapatillas/"),
            "nike": ("Nike", "/hombre/calzado-de-hombre/zapatillas/marca/nike/"),
            "running": ("Running", "/hombre/calzado-de-hombre/zapatillas-running/"),
        },
    },
}
SITE = SITES[COUNTRY]
BASE = SITE["base"]

PHOTO_WIDTH = 1600
# Vistas de la ficha: _a lateral, _b tres cuartos, _c trasera. Ni la suela (_f) ni un detalle (_d) ni la
# cenital (_e) como fotos del armario.
_VIEWS = ("a", "b", "c")
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_PRODUCT_PATH = re.compile(r"/product/([^/]+)/(\d{5,10})(?:_jdsports[a-z]*)?/?")
_LINK_TEXT = re.compile(r"(?:https?://|www\.)\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}/\S*", re.IGNORECASE)
_NOT_SHOES = re.compile(r"tong|sandale|claquette|chausson|chaussette|sandalia|chancla", re.IGNORECASE)


def next_data(page: str) -> dict:
    """El JSON de Next.js de una página. Lanza ShopError si no está (la página no es la esperada)."""
    match = _NEXT_DATA.search(page)
    if not match:
        raise ShopError("la respuesta no era la esperada (sin datos de la página)")
    try:
        data = json.loads(match.group(1))
    except ValueError as exc:
        raise ShopError("la respuesta no era la esperada (datos ilegibles)") from exc
    return data if isinstance(data, dict) else {}


def listing_results(data: dict) -> dict:
    """Los resultados que el servidor ya ha pintado: {"hits": [...], "nbHits": …}."""
    state = ((data.get("props") or {}).get("pageProps") or {}).get("searchServerState") or {}
    initial = state.get("initialResults") or {}
    for value in initial.values():
        results = (value or {}).get("results") or []
        if results and isinstance(results[0], dict):
            return results[0]
    raise ShopError("la respuesta no era la esperada (sin listado)")


def product_url(slug: str, object_id: str) -> str:
    return f"{BASE}/product/{slug}/{object_id}{SITE['suffix']}/"


def _clean_name(name: str, brand: str) -> str:
    """«On Running Cloudtilt» -> «Cloudtilt»: la marca ya se enseña aparte."""
    name = " ".join(html.unescape(name or "").split())
    if brand and name.lower().startswith(brand.lower() + " ") and len(name) > len(brand) + 2:
        name = name[len(brand) + 1:]
    return name if any(ch.islower() for ch in name) else title_case(name)


def _is_for_men(hit: dict) -> bool:
    genders = {str(g).strip().lower() for g in hit.get("gender") or []}
    return not genders or bool(genders & SITE["men"])


def make_product(*, object_id: str, name: str, brand: str, colour: str, price: float | int | None, slug: str,
                 section: str, product_ref: str | None, age_days=None, url: str | None = None) -> ShopProduct | None:
    shown_brand = brand_name(brand)
    clean = _clean_name(name, shown_brand)
    shoe_type = estimate_shoe_type(f"{name} {section}")
    try:
        cents = round(float(price) * 100)
    except (TypeError, ValueError):
        return None
    if not clean or not object_id or shoe_type is None or cents <= 0 or _NOT_SHOES.search(name or ""):
        return None
    colour = " ".join(html.unescape(colour or "").split())
    return ShopProduct(
        store="jdsports",
        product_ref=f"jdsports:{object_id}",
        name=clean,
        price_cents=cents,
        url=url or product_url(slug, object_id),
        store_color=colour[:1].upper() + colour[1:],
        section=section,
        type=shoe_type,
        category="calzado",
        color=estimate_color(colour),
        pattern=estimate_pattern(name),
        style=estimate_style(name, shoe_type),
        season=estimate_season(name, shoe_type),
        details=f"{shown_brand} {clean}".strip().lower(),
        brand=shown_brand,
        store_data={"id": object_id, "slug": slug, "ref": product_ref or None, "age": age_days},
    )


def parse_listing(results: dict, section: str) -> list[ShopProduct]:
    """De los resultados pintados por el servidor a productos, de lo más nuevo a lo más viejo."""
    products: list[ShopProduct] = []
    refs: set[str] = set()
    for hit in results.get("hits") or []:
        if not isinstance(hit, dict) or not _is_for_men(hit) or hit.get("inStock") is False:
            continue
        brand = (hit.get("brand") or [""])[0] if isinstance(hit.get("brand"), list) else str(hit.get("brand") or "")
        product = make_product(
            object_id=str(hit.get("objectID") or ""), name=str(hit.get("name") or ""), brand=brand,
            colour=str(hit.get("colour") or ""), price=hit.get("price"), slug=str(hit.get("slug") or ""),
            section=section, product_ref=str(hit.get("productRef") or "") or None, age_days=hit.get("ageDaysRound"),
        )
        if product and product.product_ref not in refs:
            refs.add(product.product_ref)
            products.append(product)

    def age(product: ShopProduct) -> float:
        value = product.store_data.get("age")
        return float(value) if isinstance(value, (int, float)) else 1e9

    return sorted(products, key=age)


def reference(store_data: dict) -> str | None:
    """La referencia de JD (la de sus fotos, «807022»); si no, su número de producto."""
    return str(store_data.get("ref") or store_data.get("id") or "") or None


def _photo(src: str) -> str:
    return f"{src}?w={PHOTO_WIDTH}&fmt=jpg&qlt=85"


def parse_product(data: dict) -> tuple[dict, ShopDetail] | None:
    """De la ficha (`props.pageProps.product`) a (datos del producto, detalle). None si no hay producto."""
    product = ((data.get("props") or {}).get("pageProps") or {}).get("product")
    if not isinstance(product, dict) or not product.get("id"):
        return None
    by_view: dict[str, str] = {}
    for image in product.get("images") or []:
        src = str((image or {}).get("src") or "")
        view = src.rsplit("_", 1)[-1] if "_" in src else ""
        if view in _VIEWS:
            by_view.setdefault(view, src)
    photos = [_photo(by_view[v]) for v in _VIEWS if v in by_view] if "a" in by_view else []
    sizes, seen = [], set()
    for variant in product.get("variants") or []:
        name = str((variant or {}).get("size") or "").strip()
        if name and name not in seen:
            seen.add(name)
            stock = (variant.get("stock") or {}).get("available", variant.get("available"))
            sizes.append({"name": name, "in_stock": bool(stock)})
    siblings = []
    for colourway in product.get("colourways") or []:
        object_id = str((colourway or {}).get("id") or "")
        path = str((colourway or {}).get("urlPath") or "")
        match = _PRODUCT_PATH.search(path)
        if not object_id or not match or any(s["product_ref"] == f"jdsports:{object_id}" for s in siblings):
            continue
        colour = str(colourway.get("colour") or "")
        siblings.append({
            "product_ref": f"jdsports:{object_id}", "name": colour[:1].upper() + colour[1:], "hex": None,
            "url": BASE + path, "store_data": {"id": object_id, "slug": match.group(1), "ref": None},
        })
    price = (product.get("minPrice") or {}).get("centAmount")
    code = str(product.get("productCode") or "")
    match = _PRODUCT_PATH.search(str(product.get("urlPath") or ""))
    colour = str(product.get("colour") or "")
    info = {
        "id": str(product["id"]),
        "name": str(product.get("name") or ""),
        "brand": str(product.get("brand") or ""),
        "colour": colour,
        "slug": match.group(1) if match else "",
        "ref": code.rsplit("/", 1)[-1] if "/" in code else None,
        "price": price / 100 if isinstance(price, int) else None,
    }
    detail = ShopDetail(
        price_cents=price if isinstance(price, int) and price > 0 else None,
        sizes=sizes,
        photo_urls=photos,
        description=" ".join(str(product.get("description") or "").replace("*", " ").split()),
        composition=" ".join(str(product.get("fabric") or "").split())[:300],
        siblings=siblings or None,
        store_color=colour[:1].upper() + colour[1:],
        store_data={"ref": info["ref"]} if info["ref"] else {},
    )
    return info, detail


def parse_query(text: str) -> tuple[str, str]:
    """(slug, número de producto) de un enlace de JD Sports (de cualquier país: el número es el mismo).
    Lanza NotThisStore con cualquier otra cosa: JD no tiene buscador que se pueda usar."""
    text = " ".join((text or "").split())
    link = _LINK_TEXT.search(text)
    if not link:
        raise NotThisStore("JD Sports solo busca por enlace de producto")
    url = link.group().rstrip(".,;)")
    parts = urlsplit(url if "://" in url else f"https://{url}")
    host = (parts.hostname or "").lower()
    if not re.fullmatch(r"(?:[a-z0-9-]+\.)*jdsports\.[a-z.]{2,6}", host):
        raise NotThisStore("Todavía no sé buscar en esa tienda")
    match = _PRODUCT_PATH.search(parts.path)
    if not match:
        raise SearchError("Ese enlace de JD Sports no es el de un producto: pega el de la página de la zapatilla")
    return match.group(1), match.group(2)


class JDSportsConnector:
    key = "jdsports"
    name = "JD Sports"
    # No se sabe qué día saca novedades: se consulta los miércoles.
    refresh_weekday = 2  # lunes = 0
    refresh_after_release = False
    language = SITE["language"]
    categories = {slug: label for slug, (label, _path) in SITE["routes"].items()}

    def __init__(self, pause: float | None = None, timeout: float | None = None):
        self.fetcher = Fetcher(
            "jdsports",
            pause=max(config.SHOP_PAUSE_SECONDS, 1.5) if pause is None else pause,
            timeout=config.SHOP_TIMEOUT_SECONDS if timeout is None else timeout,
            accept_language=SITE["accept_language"],
            use_curl=True,
        )

    def _get(self, url: str, accept: str | None = None, pause: float | None = None, curl: bool | None = None):
        if accept is None:
            return self.fetcher.get(url, pause=pause, curl=curl)
        return self.fetcher.get(url, accept=accept, pause=pause, curl=curl)

    def list_category(self, slug: str) -> list[ShopProduct]:
        _label, path = SITE["routes"][slug]
        page = self._get(BASE + path)
        if page.status != 200:
            raise ShopError(f"HTTP {page.status}")
        return parse_listing(listing_results(next_data(page.text)), slug)

    def _product(self, object_id: str, slug: str | None) -> tuple[dict, ShopDetail] | None:
        page = self._get(product_url(slug or "p", object_id))
        if page.status in (404, 410):
            return None
        if page.status != 200:
            raise ShopError(f"HTTP {page.status}")
        return parse_product(next_data(page.text))

    def detail(self, store_data: dict) -> ShopDetail | None:
        object_id = str(store_data.get("id") or "")
        if not object_id.isdigit():
            return None
        parsed = self._product(object_id, store_data.get("slug"))
        return parsed[1] if parsed else None

    def reference(self, store_data: dict) -> str | None:
        return reference(store_data)

    def search(self, query: str, limit: int = 12) -> list[ShopProduct]:
        slug, object_id = parse_query(query)
        parsed = self._product(object_id, slug)
        if not parsed:
            raise SearchError("No he encontrado esa zapatilla en JD Sports")
        info, detail = parsed
        product = make_product(
            object_id=info["id"], name=info["name"], brand=info["brand"], colour=info["colour"],
            price=info["price"], slug=info["slug"] or "p", section="", product_ref=info["ref"],
        )
        if product is None:
            raise SearchError("Eso no es calzado que quepa en el armario")
        return [product][:limit]

    def download(self, url: str) -> bytes:
        # Las fotos salen de su CDN, que sí responde a un cliente normal.
        page = self._get(url, accept=IMAGE, pause=0.5, curl=False)
        if page.status != 200 or not page.content:
            raise ShopError(f"HTTP {page.status} al bajar la foto")
        return page.content
