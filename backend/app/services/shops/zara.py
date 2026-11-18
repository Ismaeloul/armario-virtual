"""Conector de Zara (catálogo de hombre), de momento la tienda de Francia (el usuario vive allí). Sin navegador: las mismas páginas con `?ajax=true`
devuelven JSON.

Se le pide poco y despacio: una petición cada vez y con una pausa entre ellas. Si responde algo que
no es JSON, se lanza ShopError y quien llama sigue con lo demás.
"""
import re
import threading
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, urlsplit

import httpx

from ... import catalog, config
from .base import NotThisStore, SearchError, ShopDetail, ShopError, ShopProduct
from .estimate import (
    estimate_color,
    estimate_pattern,
    estimate_season,
    estimate_style,
    estimate_type,
    sentence_case,
)

# País de la tienda. Para añadir otro (España: "es"), una entrada en SITES con sus categorías.
COUNTRY = "fr"


@dataclass(frozen=True)
class ZaraSite:
    path: str  # «fr/fr»: país e idioma en las direcciones
    store_id: int  # la tienda del buscador de la web (`itxrest/.../store/<id>/query`)
    locale: str
    accept_language: str
    language: str  # idioma de los nombres: si no es "es", se traducen para enseñarlos
    # slug de la categoría -> (nombre para el usuario, tipo por defecto si el nombre del producto no lo dice)
    categories: dict


SITES = {
    # Store id 10703 sacado de la propia web (`storeId` en el JSON de una categoría), 18-11-2026.
    # Los slugs, de `https://www.zara.com/fr/fr/categories?ajax=true` (sección homme): las mismas doce
    # secciones que en España, con el mismo número de categoría.
    "fr": ZaraSite("fr/fr", 10703, "fr_FR", "fr-FR,fr;q=0.9", "fr", {
        "homme-t-shirts-l855": ("Camisetas", "camiseta"),
        "homme-t-shirts-manches-courtes-l19355": ("Camisetas de manga corta", "camiseta"),
        "homme-polos-l733": ("Polos", "polo"),
        "homme-chemises-l737": ("Camisas", "camisa"),
        "homme-sweats-l821": ("Sudaderas", "sudadera"),
        "homme-maille-l681": ("Punto", "jersey"),
        "homme-vestes-l640": ("Chaquetas", "chaqueta"),
        "man-overshirts-l3174": ("Sobrecamisas", "sobrecamisa"),
        "homme-pantalons-l838": ("Pantalones", "pantalón"),
        "homme-jeans-l659": ("Vaqueros", "vaquero"),
        "homme-bermudas-l592": ("Bermudas", "pantalón corto"),
        "homme-chaussures-baskets-l797": ("Zapatos y zapatillas", "zapatillas"),
    }),
    "es": ZaraSite("es/es", 10701, "es_ES", "es-ES,es;q=0.9", "es", {
        "hombre-camisetas-l855": ("Camisetas", "camiseta"),
        "hombre-camisetas-manga-corta-l19355": ("Camisetas de manga corta", "camiseta"),
        "hombre-polos-l733": ("Polos", "polo"),
        "hombre-camisas-l737": ("Camisas", "camisa"),
        "hombre-sudaderas-l821": ("Sudaderas", "sudadera"),
        "hombre-punto-l681": ("Punto", "jersey"),
        "hombre-chaquetas-l640": ("Chaquetas", "chaqueta"),
        "hombre-sobrecamisas-l3174": ("Sobrecamisas", "sobrecamisa"),
        "hombre-pantalones-l838": ("Pantalones", "pantalón"),
        "hombre-jeans-l659": ("Vaqueros", "vaquero"),
        "hombre-bermudas-l592": ("Bermudas", "pantalón corto"),
        "hombre-zapatos-zapatillas-l797": ("Zapatos y zapatillas", "zapatillas"),
    }),
}
SITE = SITES[COUNTRY]

BASE = f"https://www.zara.com/{SITE.path}"
MEDIA = "https://static.zara.net"
# El buscador de la web. Solo se usa para el texto libre, y solo en hombre: una referencia o un enlace
# van directos a la ficha, sea de la sección que sea.
SEARCH = f"https://www.zara.com/itxrest/1/search/store/{SITE.store_id}/query"
TEXT_RESULTS = 6  # de cada resultado de texto hay que pedir luego la ficha: pocos, para no hacer esperar
PAGE_CACHE_SECONDS = 300  # lo que se recuerda la ficha recién buscada, para no pedirla otra vez por color
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": SITE.accept_language,
}

# slug de la categoría -> (nombre para el usuario, tipo por defecto si el nombre del producto no lo dice).
# Los de cualquier país: un producto guardado con otro país sigue sabiendo su tipo por defecto.
CATEGORIES = {**SITES["es"].categories, **SITE.categories}

_PRODUCT_PHOTO = re.compile(r"-e(\d+)$")  # las fotos de producto sin modelo: -e1 (delante), -e2 (detrás)…
_AVAILABLE = ("in_stock", "low_on_stock")
MAX_PHOTOS = 3
PHOTO_WIDTH = 1280


def product_url(keyword: str, seo_id: str, discern_id) -> str:
    return f"{BASE}/{keyword}-p{seo_id}.html?v1={discern_id}"


def parse_category(data: dict, slug: str) -> list[ShopProduct]:
    """Del JSON de una categoría a productos normalizados. Lo que no es una prenda del armario se salta."""
    default_type = CATEGORIES.get(slug, ("", None))[1]
    products: list[ShopProduct] = []
    refs: set[str] = set()
    for group in data.get("productGroups") or []:
        for element in group.get("elements") or []:
            for item in element.get("commercialComponents") or []:
                product = _parse_product(item, slug, default_type)
                if product and product.product_ref not in refs:
                    refs.add(product.product_ref)
                    products.append(product)
    return products


def _parse_product(item: dict, slug: str, default_type: str | None) -> ShopProduct | None:
    seo = item.get("seo") or {}
    name = (item.get("name") or "").strip()
    if not name or item.get("type") != "Product" or not seo.get("seoProductId") or not seo.get("keyword"):
        return None
    price = item.get("price")
    if not isinstance(price, int) or price <= 0:
        return None
    garment_type = estimate_type(name, default_type)
    if garment_type is None:
        return None

    # A veces el «keyword» trae un espacio (incluso de no separación) donde va un guion.
    keyword = "-".join(seo["keyword"].split())
    color = ((item.get("detail") or {}).get("colors") or [{}])[0]
    store_color = (color.get("name") or "").strip()
    discern_id = seo.get("discernProductId") or item.get("id")
    color_id = str(color.get("id") or discern_id)
    details = name.lower()
    if ("manga-corta" in slug or "manches-courtes" in slug) and "manga" not in details and "manche" not in details:
        details += " manga corta"
    return ShopProduct(
        store="zara",
        product_ref=f"zara:{seo['seoProductId']}-{color_id}",
        name=sentence_case(name),
        price_cents=price,
        url=product_url(keyword, seo["seoProductId"], discern_id),
        store_color=store_color,
        section=slug,
        type=garment_type,
        category=catalog.category_of(garment_type),
        color=estimate_color(store_color),
        pattern=estimate_pattern(name),
        style=estimate_style(name, garment_type),
        season=estimate_season(name, garment_type),
        details=details,
        store_data={
            "keyword": keyword,
            "seo_id": seo["seoProductId"],
            "discern_id": discern_id,
            "color_id": color_id,
        },
    )


# ---------- El buscador: de lo que escribe el usuario a qué pedirle a Zara


@dataclass
class ZaraQuery:
    """Lo que se busca: un producto concreto (por su referencia o su enlace) o texto libre."""

    seo_id: str | None = None  # «03918300»: el modelo (4 cifras) y la calidad (3) con un cero delante
    color_id: str | None = None  # «800», si la referencia lo trae
    v1: str | None = None  # el id del color en el enlace (`?v1=`), si lo trae
    text: str | None = None  # texto libre («cazadora lana negra»)


_LINK = re.compile(r"(?:https?://|www\.)\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}/\S*", re.IGNORECASE)
_LINK_REF = re.compile(r"-p(\d{7,8})(?:\.html|\b)", re.IGNORECASE)
_REF_WORDS = re.compile(r"\b(?:referencia|ref|art[ií]culo|art|modelo|n[uú]mero|num|zara)\b|[nN][ºo°]\.?")
_NOT_A_REF = "Eso no parece una referencia de Zara: son 7 cifras, tipo 3918/300"


def parse_query(text: str) -> ZaraQuery:
    """De lo que el usuario escribe o pega a lo que se busca. Vale:

    - una referencia en cualquiera de sus formas: «3918/300», «3918/300/800», «03918300»,
      «0391 8300 800» (la de la etiqueta), «REF. 3918/300»;
    - un enlace de producto de zara.com, también el que comparte la app, mientras lleve el
      `-p03918300` (y el `v1` del color, si viene), aunque venga dentro de una frase;
    - cualquier otra cosa con letras, como texto libre.

    Lanza NotThisStore si es un enlace de otra tienda y SearchError si no hay por dónde cogerlo.
    """
    text = " ".join((text or "").split())
    link = _LINK.search(text)
    if link:
        url = link.group().rstrip(".,;)")
        parts = urlsplit(url if "://" in url else f"https://{url}")
        host = (parts.hostname or "").lower()
        if host != "zara.com" and not host.endswith(".zara.com"):
            raise NotThisStore("Todavía no sé buscar en esa tienda")
        ref = _LINK_REF.search(parts.path)
        if not ref:
            raise SearchError("Ese enlace de Zara no lleva la referencia del producto: escríbela a mano (tipo 3918/300)")
        v1 = (parse_qs(parts.query).get("v1") or [""])[0]
        return ZaraQuery(seo_id=ref.group(1).zfill(8), v1=v1 if v1.isdigit() else None)

    bare = _REF_WORDS.sub(" ", text.lower())
    if not re.search(r"[^\W\d_]", bare):  # no queda ninguna letra: solo puede ser una referencia
        digits = re.sub(r"\D", "", bare)
        if not digits:
            raise SearchError("Escribe una referencia, un enlace de Zara o qué prenda buscas")
        if re.search(r"[^\d\s/.\-_·:#]", bare):
            raise SearchError(_NOT_A_REF)
        if len(digits) in (7, 8):  # modelo + calidad, con o sin el cero de delante
            return ZaraQuery(seo_id=digits.zfill(8))
        if len(digits) in (10, 11):  # … y el color detrás
            return ZaraQuery(seo_id=digits[:-3].zfill(8), color_id=digits[-3:])
        raise SearchError(_NOT_A_REF)
    if len(text) < 3:
        raise SearchError("Escribe una referencia, un enlace de Zara o qué prenda buscas")
    return ZaraQuery(text=text[:80])


def _family_type(item: dict) -> str | None:
    """El tipo que dice la familia de Zara («CAZADORA», «JERSEY»), por si el nombre no lo dice."""
    return estimate_type(f"{item.get('familyName') or ''} {item.get('subfamilyName') or ''}")


def parse_search(data: dict, limit: int) -> list[ShopProduct]:
    """De la respuesta del buscador de Zara a productos. Cada resultado es un color de un producto,
    con la misma forma que en el listado de una categoría."""
    products: list[ShopProduct] = []
    refs: set[str] = set()
    for result in data.get("results") or []:
        item = (result or {}).get("content") or {}
        product = _parse_product(item, "", _family_type(item))
        if product and product.product_ref not in refs:
            refs.add(product.product_ref)
            products.append(product)
            if len(products) >= limit:
                break
    return products


def parse_product_page(data: dict, wanted: ZaraQuery, limit: int) -> list[ShopProduct]:
    """De la ficha de un producto a un resultado por color. Si se pidió un color (el de la
    referencia) y existe, solo ese; el del enlace (`v1`) va el primero."""
    product = data.get("product") or {}
    seo = product.get("seo") or {}
    colors = [c for c in (product.get("detail") or {}).get("colors") or [] if isinstance(c, dict)]
    exact = [c for c in colors if wanted.color_id and str(c.get("id")) == wanted.color_id]
    colors = exact or sorted(colors, key=lambda c: str(c.get("productId")) != str(wanted.v1))
    default_type = _family_type(product)
    found: list[ShopProduct] = []
    for color in colors:
        item = {
            **product,
            "price": color.get("price"),
            "detail": {"colors": [color]},
            "seo": {**seo, "discernProductId": color.get("productId") or seo.get("discernProductId")},
        }
        parsed = _parse_product(item, "", default_type)
        if parsed and all(parsed.product_ref != other.product_ref for other in found):
            found.append(parsed)
    return found[:limit]


def photo_url(media: dict) -> str:
    path = (media.get("path") or "").removeprefix("/assets/public/").strip("/")
    return f"{MEDIA}/assets/public/{path}/{media['name']}.jpg?w={PHOTO_WIDTH}"


def reference(store_data: dict) -> str | None:
    """«3918/300/800»: modelo, calidad y color, como en la etiqueta y en la web. Sin el color si no
    se conoce (o no es uno de los de tres cifras)."""
    seo_id = str(store_data.get("seo_id") or "")
    if not seo_id.isdigit() or len(seo_id) < 7:
        return None
    parts = [seo_id[:-3].lstrip("0") or "0", seo_id[-3:]]
    color_id = str(store_data.get("color_id") or "")
    if re.fullmatch(r"\d{3}", color_id):
        parts.append(color_id)
    return "/".join(parts)


def _product_photos(color: dict) -> list[str]:
    """Las fotos de producto (sin modelo) de un color, en orden. Sin la -e1 no hay ninguna que enseñar."""
    numbered: dict[int, dict] = {}
    for media in color.get("xmedia") or []:
        match = _PRODUCT_PHOTO.search(media.get("name") or "")
        if match and media.get("type", "image") == "image" and media.get("path"):
            numbered.setdefault(int(match.group(1)), media)
    return [photo_url(numbered[n]) for n in sorted(numbered)][:MAX_PHOTOS] if 1 in numbered else []


def _hex(color: dict) -> str | None:
    code = color.get("hexCode")
    return code.lower() if isinstance(code, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", code) else None


def parse_siblings(data: dict, store_data: dict) -> list[dict]:
    """Todos los colores de la ficha que tienen foto de producto, con lo necesario para pedir cada uno."""
    product = data.get("product") or {}
    seo = product.get("seo") or {}
    seo_id = str(store_data.get("seo_id") or seo.get("seoProductId") or "")
    keyword = store_data.get("keyword") or "-".join(str(seo.get("keyword") or "").split())
    siblings: list[dict] = []
    for color in (product.get("detail") or {}).get("colors") or []:
        if not isinstance(color, dict) or not _product_photos(color):
            continue
        discern_id = color.get("productId") or store_data.get("discern_id")
        color_id = str(color.get("id") or discern_id)
        ref = f"zara:{seo_id}-{color_id}"
        if not seo_id or not keyword or any(other["product_ref"] == ref for other in siblings):
            continue
        siblings.append({
            "product_ref": ref,
            "name": (color.get("name") or "").strip(),
            "hex": _hex(color),
            "price_cents": color.get("price") if isinstance(color.get("price"), int) else None,
            "url": product_url(keyword, seo_id, discern_id),
            "store_data": {"keyword": keyword, "seo_id": seo_id, "discern_id": discern_id, "color_id": color_id},
        })
    return siblings


def _full_composition(data: dict) -> str:
    """La composición entera, por partes: «Exterior: 55% poliéster, 45% lana · Forro: 100% poliéster»."""
    composition = ((data.get("product") or {}).get("detail") or {}).get("detailedComposition") or {}
    parts: list[str] = []
    for part in composition.get("parts") or []:
        if not isinstance(part, dict):
            continue
        components: list[str] = []
        # Algunas partes traen los tejidos dentro de «areas» (el cuerpo y las mangas, por ejemplo).
        groups = [part] + [area for area in part.get("areas") or [] if isinstance(area, dict)]
        for group in groups:
            for component in group.get("components") or []:
                if not isinstance(component, dict):
                    continue
                material = str(component.get("material") or "").strip().lower()
                text = f"{str(component.get('percentage') or '').strip()} {material}".strip()
                if material and text not in components:
                    components.append(text)
        if components:
            label = sentence_case(str(part.get("description") or "").strip())
            parts.append(f"{label}: {', '.join(components)}" if label else ", ".join(components))
    return " · ".join(parts)[:300]


def _composition(data: dict) -> str:
    """Los tejidos que son al menos la mitad de la prenda («100% lino»): la descripción no siempre los
    nombra, y el lino o la lana dicen de qué temporada es."""
    composition = ((data.get("product") or {}).get("detail") or {}).get("detailedComposition") or {}
    materials: list[str] = []
    for part in composition.get("parts") or []:
        for component in part.get("components") or []:
            material = str(component.get("material") or "").strip().lower()
            match = re.match(r"\d+", str(component.get("percentage") or ""))
            if material and match and int(match.group()) >= 50 and material not in materials:
                materials.append(material)
    return f"Tejido principal: {', '.join(materials)}." if materials else ""


def parse_detail(data: dict, store_data: dict) -> ShopDetail | None:
    """De la ficha de un producto a tallas y fotos del color que nos interesa. None si no trae colores."""
    colors = ((data.get("product") or {}).get("detail") or {}).get("colors") or []
    if not colors:
        return None
    color = next(
        (c for c in colors if str(c.get("productId")) == str(store_data.get("discern_id"))),
        next((c for c in colors if str(c.get("id")) == str(store_data.get("color_id"))), colors[0]),
    )
    # Sin la foto -e1 no hay foto de producto que enseñar: quien llama lo descarta.
    photos = _product_photos(color)

    sizes, names = [], set()
    for size in color.get("sizes") or []:
        size_name = str(size.get("name") or "").strip()
        if size_name and size_name not in names:
            names.add(size_name)
            sizes.append({"name": size_name, "in_stock": size.get("availability") in _AVAILABLE})
    price = color.get("price")
    seo =(data.get("product") or {}).get("seo") or {}
    description = (color.get("description") or color.get("rawDescription") or seo.get("description") or "").strip()
    return ShopDetail(
        price_cents=price if isinstance(price, int) and price > 0 else None,
        sizes=sizes,
        photo_urls=photos,
        description=" ".join(part for part in (description, _composition(data)) if part),
        color_hex=_hex(color),
        composition=_full_composition(data),
        siblings=parse_siblings(data, store_data),
    )


class ZaraConnector:
    key = "zara"
    name = "Zara"
    # Zara saca novedades los jueves (según la prensa de moda; no es un dato oficial): se consulta los viernes.
    refresh_weekday = 4  # lunes = 0
    refresh_after_release = True  # el día de consulta sale de cuándo saca novedades
    language = SITE.language
    categories = {slug: label for slug, (label, _default) in SITE.categories.items()}

    def __init__(self, pause: float | None = None, timeout: float | None = None, pages: int | None = None):
        self.pause = config.SHOP_PAUSE_SECONDS if pause is None else pause
        self.timeout = config.SHOP_TIMEOUT_SECONDS if timeout is None else timeout
        # El listado va de 20 en 20 y `page=N` devuelve las N primeras páginas juntas, en una sola petición.
        self.pages = config.SHOP_PAGES if pages is None else pages
        self._client: httpx.Client | None = None
        self._lock = threading.Lock()  # una petición cada vez
        self._last = 0.0
        self.requests = 0
        self._pages: dict[str, tuple[float, dict]] = {}  # seo_id -> (cuándo, la ficha recién buscada)

    def _get(self, url: str, pause: float, headers: dict | None = None) -> httpx.Response:
        with self._lock:
            if self._client is None:
                self._client = httpx.Client(headers=HEADERS, timeout=self.timeout, follow_redirects=True)
            wait = self._last + pause - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                self.requests += 1
                return self._client.get(url, headers=headers)
            except httpx.TimeoutException as exc:
                raise ShopError(f"tiempo agotado ({self.timeout:g} s)") from exc
            except httpx.HTTPError as exc:
                raise ShopError(f"no se pudo conectar ({type(exc).__name__})") from exc
            finally:
                self._last = time.monotonic()

    def _json(self, url: str, follow: bool = True) -> dict | None:
        """El JSON de una página. None si la página ya no existe (404 o 410)."""
        response = self._get(url, self.pause)
        if response.status_code in (404, 410):
            return None
        if response.status_code == 278 and follow:
            # La redirección de Zara para las peticiones ajax: {"location": "<la dirección buena>"}.
            try:
                location = response.json().get("location")
            except (ValueError, AttributeError):
                location = None
            if isinstance(location, str) and location.startswith(BASE + "/"):
                return self._json(location, follow=False)
        if response.status_code != 200:
            raise ShopError(f"HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise ShopError("la respuesta no era la esperada (no es JSON)") from exc
        if not isinstance(data, dict):
            raise ShopError("la respuesta no era la esperada (JSON con otra forma)")
        return data

    def list_category(self, slug: str) -> list[ShopProduct]:
        # Pedir más páginas de las que tiene la categoría da 404 (comprobado con Camisetas, que solo
        # tiene dos): se va bajando hasta dar con las que hay.
        data = None
        for pages in range(max(self.pages, 1), 0, -1):
            page = f"&page={pages}" if pages > 1 else ""
            data = self._json(f"{BASE}/{slug}.html?ajax=true{page}")
            if data is not None:
                break
        if data is None:
            raise ShopError("HTTP 404 o 410: la categoría ya no existe")
        return parse_category(data, slug)

    def _product_page(self, seo_id: str) -> dict | None:
        """La ficha de un producto a partir solo de su referencia. None si Zara no la conoce.

        `-p03918300.html` sin el nombre delante responde con un 278 hacia la dirección buena; si la
        referencia no existe, el 278 manda a la portada.
        """
        response = self._get(f"{BASE}/-p{seo_id}.html?ajax=true", self.pause)
        if response.status_code in (404, 410):
            return None
        if response.status_code == 278:
            try:
                location = response.json().get("location")
            except (ValueError, AttributeError):
                location = None
            if not isinstance(location, str) or not location.startswith(BASE + "/") or f"-p{seo_id}." not in location:
                return None
            if "ajax=true" not in location:
                location += ("&" if "?" in location else "?") + "ajax=true"
            data = self._json(location, follow=False)
        elif response.status_code == 200:
            try:
                data = response.json()
            except ValueError as exc:
                raise ShopError("la respuesta no era la esperada (no es JSON)") from exc
        else:
            raise ShopError(f"HTTP {response.status_code}")
        return data if isinstance(data, dict) and isinstance(data.get("product"), dict) else None

    def search(self, query: str, limit: int = 12) -> list[ShopProduct]:
        wanted = parse_query(query)
        if wanted.seo_id is None:
            url = f"{SEARCH}?query={quote(wanted.text)}&locale={SITE.locale}&section=MAN&offset=0&limit={TEXT_RESULTS * 2}"
            products = parse_search(self._json(url, follow=False) or {}, min(limit, TEXT_RESULTS))
            if not products:
                raise SearchError(f"No he encontrado nada en Zara con «{wanted.text}»")
            return products
        data = self._product_page(wanted.seo_id)
        if data is None:
            raise SearchError("No he encontrado nada con esa referencia")
        products = parse_product_page(data, wanted, limit)
        if not products:
            name = sentence_case((data["product"].get("name") or "").strip()) or "Eso"
            raise SearchError(f"«{name}» no es un tipo de prenda que quepa en el armario")
        # La ficha trae ya las tallas y las fotos de todos los colores: se guarda un rato para `detail`.
        now = time.monotonic()
        self._pages = {k: v for k, v in self._pages.items() if now - v[0] < PAGE_CACHE_SECONDS}
        self._pages[wanted.seo_id] = (now, data)
        return products

    def reference(self, store_data: dict) -> str | None:
        return reference(store_data)

    def detail(self, store_data: dict) -> ShopDetail | None:
        cached = self._pages.get(str(store_data.get("seo_id")))
        if cached and time.monotonic() - cached[0] < PAGE_CACHE_SECONDS:
            return parse_detail(cached[1], store_data)
        url = product_url(store_data["keyword"], store_data["seo_id"], store_data["discern_id"]) + "&ajax=true"
        data = self._json(url)
        return parse_detail(data, store_data) if data is not None else None

    def download(self, url: str) -> bytes:
        # Las fotos salen de la CDN, no de la web: basta una pausa corta.
        response = self._get(
            url, min(self.pause, 0.25), headers={"Referer": "https://www.zara.com/", "Accept": "image/*"}
        )
        if response.status_code != 200 or not response.content:
            raise ShopError(f"HTTP {response.status_code} al bajar la foto")
        return response.content
