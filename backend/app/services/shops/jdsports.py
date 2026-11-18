"""Conector de JD Sports (de momento jdsports.fr): zapatillas de hombre de muchas marcas.

Se lee CON NAVEGADOR (browser.py), como Pull&Bear y Bershka: desde el Umbrel (Linux, Docker) la web
responde 403 a curl y a httpx en casi todo (un filtro por la huella del cliente), y a un Chromium de
serie con su ventana, no. No se imita ninguna huella: es el navegador de verdad.

- Los datos van en el `__NEXT_DATA__` de cada página (Next.js): se abre la página en el navegador y se
  lee ese JSON de la página ya cargada, nada de lo que pinta. El servidor pinta 72 productos por
  página en el orden «recomendados». Las páginas siguientes son las que abre el propio botón
  «Charger plus» de la web (`?from=72`, `?from=144`…, que el servidor también pinta): se leen hasta
  PAGES por ruta. Para cubrir más catálogo se recorren varias rutas (novedades, subcategorías y marcas)
  y se ordena en local por antigüedad (`ageDaysRound`). El servicio de búsqueda de terceros que usa la
  web en el cliente NO se consulta nunca.
- La ficha, igual: la página del producto en el navegador y su `__NEXT_DATA__`. Las fotos, de su CDN
  (otro dominio, que responde a un cliente normal), con httpx.
- Sin buscador: el navegador no se abre dentro de una petición HTTP. A un enlace de JD se le explica.
"""
import html
import re
from urllib.parse import urlsplit

from ... import config
from . import browser
from .base import BlockedError, NeedsBrowser, NotThisStore, SearchError, ShopDetail, ShopError, ShopProduct
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
PAGES = 3  # páginas de 72 por ruta: las que abriría el botón «Charger plus» de la web
PER_PAGE = 72  # lo que pinta el servidor por página (la propia página lo dice en `hitsPerPage`)
# Vistas de la ficha: _a lateral, _b tres cuartos, _c trasera. Ni la suela (_f) ni un detalle (_d) ni la
# cenital (_e) como fotos del armario.
_VIEWS = ("a", "b", "c")
_PRODUCT_PATH = re.compile(r"/product/([^/]+)/(\d{5,10})(?:_jdsports[a-z]*)?/?")
_LINK_TEXT = re.compile(r"(?:https?://|www\.)\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}/\S*", re.IGNORECASE)
_NOT_SHOES = re.compile(r"tong|sandale|claquette|chausson|chaussette|sandalia|chancla", re.IGNORECASE)


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
                 section: str, product_ref: str | None, age_days=None) -> ShopProduct | None:
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
        url=product_url(slug, object_id),
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


def parse_product(data: dict) -> ShopDetail | None:
    """De la ficha (`props.pageProps.product`) a su detalle. None si no hay producto (ya no existe y la
    tienda ha llevado a otra página)."""
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
    ref = code.rsplit("/", 1)[-1] if "/" in code else None
    colour = str(product.get("colour") or "")
    return ShopDetail(
        price_cents=price if isinstance(price, int) and price > 0 else None,
        sizes=sizes,
        photo_urls=photos,
        description=" ".join(str(product.get("description") or "").replace("*", " ").split()),
        composition=" ".join(str(product.get("fabric") or "").split())[:300],
        siblings=siblings or None,
        store_color=colour[:1].upper() + colour[1:],
        store_data={"ref": ref} if ref else {},
    )


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


def page_url(path: str, index: int, per_page: int = PER_PAGE) -> str:
    """La página `index` (desde 0) de una ruta: la misma dirección que deja el botón «Charger plus»."""
    return BASE + path + (f"?from={index * per_page}" if index else "")


class JDSportsConnector:
    key = "jdsports"
    name = "JD Sports"
    needs_browser = True
    # No se sabe qué día saca novedades: se consulta los miércoles.
    refresh_weekday = 2  # lunes = 0
    refresh_after_release = False
    language = SITE["language"]
    categories = {slug: label for slug, (label, _path) in SITE["routes"].items()}

    def __init__(self, pages: int = PAGES):
        self.pages = pages
        # Las fotos, de la CDN: un cliente normal, con su pausa corta.
        self.fetcher = Fetcher("jdsports", pause=0.3, timeout=config.SHOP_TIMEOUT_SECONDS,
                               accept_language=SITE["accept_language"])

    def _read(self, url: str) -> tuple[int | None, dict | None]:
        """(estado, `__NEXT_DATA__`) de una página de la tienda, abierta en el navegador."""
        status, data = browser.require(self.key).page_json(self.key, url)
        return status, data if isinstance(data, dict) else None

    def list_category(self, slug: str) -> list[ShopProduct]:
        _label, path = SITE["routes"][slug]
        hits: list = []
        per_page = PER_PAGE
        for index in range(self.pages):
            try:
                status, data = self._read(page_url(path, index, per_page))
                if status != 200 or data is None:
                    raise ShopError(f"HTTP {status}")
                results = listing_results(data)
            except ShopError as exc:
                # Un bloqueo para la tienda entera; si falla una página siguiente, basta con lo que hay.
                if index == 0 or isinstance(exc, BlockedError):
                    raise
                break
            if results.get("page") not in (None, index):
                break  # el servidor no ha dado la página pedida: no se insiste
            hits += results.get("hits") or []
            if isinstance(results.get("hitsPerPage"), int) and results["hitsPerPage"] > 0:
                per_page = results["hitsPerPage"]
            pages = results.get("nbPages")
            if isinstance(pages, int) and index + 1 >= pages:
                break
        return parse_listing({"hits": hits}, slug)

    def detail(self, store_data: dict) -> ShopDetail | None:
        object_id = str(store_data.get("id") or "")
        if not object_id.isdigit():
            return None
        if not browser.active():  # una petición HTTP normal (elegir otro color): aquí no se abre
            raise NeedsBrowser(f"{self.name} solo se lee con navegador, en las consultas en segundo plano: "
                               "ese color no se puede traer ahora")
        status, data = self._read(product_url(store_data.get("slug") or "p", object_id))
        if status in (404, 410):
            return None
        if status != 200 or data is None:
            raise ShopError(f"HTTP {status}")
        return parse_product(data)

    def reference(self, store_data: dict) -> str | None:
        return reference(store_data)

    def search(self, query: str, limit: int = 12) -> list[ShopProduct]:
        """Sin buscador: el navegador no se abre dentro de una petición HTTP. A un enlace de JD se le
        explica por qué; lo demás no es cosa suya."""
        parse_query(query)  # NotThisStore si no es un enlace de JD; SearchError si no es de un producto
        raise SearchError(
            f"{self.name} solo se lee con navegador en las consultas semanales: el buscador no la abre. "
            "Actívala en Tiendas y saldrá en Descubrir si está en sus secciones."
        )

    def download(self, url: str) -> bytes:
        # Las fotos salen de su CDN, que sí responde a un cliente normal.
        page = self.fetcher.get(url, accept=IMAGE)
        if page.status != 200 or not page.content:
            raise ShopError(f"HTTP {page.status} al bajar la foto")
        return page.content
