"""Conector de Zara España (catálogo de hombre). Sin navegador: las mismas páginas con `?ajax=true`
devuelven JSON.

Se le pide poco y despacio: una petición cada vez y con una pausa entre ellas. Si responde algo que
no es JSON, se lanza ShopError y quien llama sigue con lo demás.
"""
import re
import threading
import time

import httpx

from ... import catalog, config
from .base import ShopDetail, ShopError, ShopProduct
from .estimate import (
    estimate_color,
    estimate_pattern,
    estimate_season,
    estimate_style,
    estimate_type,
    sentence_case,
)

BASE = "https://www.zara.com/es/es"
MEDIA = "https://static.zara.net"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "es-ES,es;q=0.9",
}

# slug de la categoría -> (nombre para el usuario, tipo por defecto si el nombre del producto no lo dice)
CATEGORIES = {
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
}

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
    if "manga-corta" in slug and "manga" not in details:
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


def photo_url(media: dict) -> str:
    path = (media.get("path") or "").removeprefix("/assets/public/").strip("/")
    return f"{MEDIA}/assets/public/{path}/{media['name']}.jpg?w={PHOTO_WIDTH}"


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
    numbered: dict[int, dict] = {}
    for media in color.get("xmedia") or []:
        match = _PRODUCT_PHOTO.search(media.get("name") or "")
        if match and media.get("type", "image") == "image" and media.get("path"):
            numbered.setdefault(int(match.group(1)), media)
    # Sin la foto -e1 no hay foto de producto que enseñar: quien llama lo descarta.
    photos = [photo_url(numbered[n]) for n in sorted(numbered)][:MAX_PHOTOS] if 1 in numbered else []

    sizes, names = [], set()
    for size in color.get("sizes") or []:
        size_name = str(size.get("name") or "").strip()
        if size_name and size_name not in names:
            names.add(size_name)
            sizes.append({"name": size_name, "in_stock": size.get("availability") in _AVAILABLE})
    price = color.get("price")
    hex_code = color.get("hexCode")
    seo = (data.get("product") or {}).get("seo") or {}
    description = (color.get("description") or color.get("rawDescription") or seo.get("description") or "").strip()
    return ShopDetail(
        price_cents=price if isinstance(price, int) and price > 0 else None,
        sizes=sizes,
        photo_urls=photos,
        description=" ".join(part for part in (description, _composition(data)) if part),
        color_hex=hex_code.lower() if isinstance(hex_code, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", hex_code) else None,
    )


class ZaraConnector:
    key = "zara"
    name = "Zara"
    # Zara saca novedades los jueves (según la prensa de moda; no es un dato oficial): se consulta los viernes.
    refresh_weekday = 4  # lunes = 0
    categories = {slug: label for slug, (label, _default) in CATEGORIES.items()}

    def __init__(self, pause: float | None = None, timeout: float | None = None, pages: int | None = None):
        self.pause = config.SHOP_PAUSE_SECONDS if pause is None else pause
        self.timeout = config.SHOP_TIMEOUT_SECONDS if timeout is None else timeout
        # El listado va de 20 en 20 y `page=N` devuelve las N primeras páginas juntas, en una sola petición.
        self.pages = config.SHOP_PAGES if pages is None else pages
        self._client: httpx.Client | None = None
        self._lock = threading.Lock()  # una petición cada vez
        self._last = 0.0
        self.requests = 0

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

    def detail(self, store_data: dict) -> ShopDetail | None:
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
