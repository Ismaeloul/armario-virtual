"""Conector de Nike (nike.com/fr): SOLO zapatillas de hombre.

Sin navegador (investigado el 18-11-2026: httpx con cabeceras normales, 200 en todo; Akamai detrás pero
sin desafíos). Si un día deja de responder a un cliente normal (como JD Sports en el Umbrel), basta con
poner `needs_browser = True`: las páginas se leen igual, abiertas en el navegador (ver fetch.read_html).

- Listado: la página de la sección (`/fr/w/hommes-chaussures-nik1zy7ok?sortBy=newest`, lo más nuevo
  primero) trae en su `__NEXT_DATA__` los 24 primeros modelos (`Wall.productGroupings`, un producto por
  color) y `pageData.next`: la dirección que la propia página pide al desplazarse para los 24 siguientes
  (en api.nike.com, con el mismo JSON y su propio `next`). Se sigue hasta que no hay `next` (~33 páginas).
  Esa dirección la da la página; no se le añade ninguna cabecera ni identificador copiado del navegador.
- Ficha: el `__NEXT_DATA__` de la página del producto (`selectedProduct`): precio, descripción, fotos
  (`contentImages`: en calzado, todas sin modelo) y los otros colores (`colorwayImages`).
- Tallas: la página no dice cuáles quedan (las enseña todas como «ACTIVE»; el stock lo pide aparte a
  una API interna que NO se llama, por decisión firme). Así que la zapatilla sale SIN tallas y cuenta
  como disponible mientras la tienda la venda (`statusModifier` «BUYABLE…»).
- Referencia: el código de fabricante, el de la caja y la web («HM6803-019»).
- Buscador: por referencia o enlace (`/fr/t/x/<código>` redirige a la ficha). Sin texto libre: el
  buscador de la web está prohibido en su robots.txt.
"""
import json
import re
from urllib.parse import urlsplit

from ... import config
from . import crawl
from .base import NotThisStore, SearchError, ShopDetail, ShopError, ShopProduct
from .estimate import brand_name, estimate_color, estimate_pattern, estimate_season, estimate_shoe_type
from .estimate import estimate_style
from .fetch import IMAGE, Fetcher, read_html, read_json

BASE = "https://www.nike.com"
API = "https://api.nike.com"
SORT = "sortBy=newest"
# slug -> (nombre para el usuario, ruta). Todo el calzado de hombre: Lifestyle, Jordan, Running… ya van dentro.
CATEGORIES = {
    "chaussures": ("Zapatillas", "/fr/w/hommes-chaussures-nik1zy7ok"),
}
MAX_PHOTOS = 4
# Vistas de la ficha (comprobado en una zapatilla, la Vomero 18): 1 lateral, 2 suela, 3 lateral interior,
# 4 el par desde arriba, 5 el par en tres cuartos, 6 trasera. Para el armario: lateral, tres cuartos,
# desde arriba y trasera. La suela nunca. Si una ficha trae otras, se rellena por orden.
PHOTO_ORDER = (0, 4, 3, 5, 2)
SEARCH_RESULTS = 6

_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
# Lo que no es calzado del armario: chanclas, sandalias, zapatillas de casa… y las de competición (clavos de
# atletismo, botas de fútbol con tacos).
_NOT_SHOES = re.compile(r"sandale|claquette|\btongs?\b|\bmules?\b|\bslides?\b|chausson|chaussette|\bsocks?\b|"
                        r"pointes|crampons|\bspikes?\b", re.IGNORECASE)
# El código de Nike: dos letras y cuatro cifras (HM6803) o seis cifras (555088, las Jordan de siempre), y el
# color (-019). Más estricto que «cualquier código»: el buscador pregunta a todas las tiendas, y el de
# unas ASICS (1203A739-200) no tiene que acabar en Nike.
_CODE = re.compile(r"(?:[A-Z]{2}\d{4}|\d{6})-\d{3}")
_LINK_TEXT = re.compile(r"(?:https?://|www\.)\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}/\S*", re.IGNORECASE)


def _clean(text) -> str:
    """Sin los espacios finos o no separables de sus nombres («Vomero 18»)."""
    return " ".join(str(text or "").replace(" ", " ").replace("\xa0", " ").split())


def next_data(page: str) -> dict:
    match = _NEXT_DATA.search(page or "")
    if not match:
        raise ShopError("la respuesta no era la esperada (sin datos de la página)")
    try:
        data = json.loads(match.group(1))
    except ValueError as exc:
        raise ShopError("la respuesta no era la esperada (datos ilegibles)") from exc
    return data if isinstance(data, dict) else {}


def wall(data: dict) -> dict:
    """El listado que pinta el servidor: {"productGroupings": [...], "pageData": {"next", "totalPages"…}}."""
    found = (((data.get("props") or {}).get("pageProps") or {}).get("initialState") or {}).get("Wall")
    if not isinstance(found, dict):
        raise ShopError("la respuesta no era la esperada (sin listado)")
    return found


def _brand_and_name(title: str) -> tuple[str, str]:
    """«Nike Vomero 18» -> («Nike», «Vomero 18»); «Jordan Spizike Low» -> («Jordan», «Spizike Low»);
    «Air Jordan 1 Low» -> («Jordan», «Air Jordan 1 Low»)."""
    title = _clean(title)
    low = title.lower()
    if low.startswith("jordan "):
        return "Jordan", title[7:]
    if "jordan" in low.split():
        return "Jordan", title
    if low.startswith("nike ") and len(title) > 6:
        return "Nike", title[5:]
    return "Nike", title


def _cents(value) -> int | None:
    try:
        cents = round(float(value) * 100)
    except (TypeError, ValueError):
        return None
    return cents if cents > 0 else None


def make_product(item: dict, section: str) -> ShopProduct | None:
    """Un color del listado (o de una ficha suelta). None si no es calzado del armario."""
    if not isinstance(item, dict) or str(item.get("productType") or "FOOTWEAR").upper() != "FOOTWEAR":
        return None
    code = str(item.get("productCode") or item.get("styleColor") or "").strip()
    copy = item.get("copy") or {}
    title = _clean(copy.get("title") or (item.get("productInfo") or {}).get("title"))
    subtitle = _clean(copy.get("subTitle") or (item.get("productInfo") or {}).get("subtitle"))
    price = _cents((item.get("prices") or {}).get("currentPrice"))
    pdp = item.get("pdpUrl") or {}
    url = str(pdp.get("url") if isinstance(pdp, dict) else pdp or "")
    if not _CODE.fullmatch(code) or not title or price is None or _NOT_SHOES.search(f"{title} {subtitle}"):
        return None  # sin código de modelo de verdad es una «Nike By You» (se diseña en la web): fuera
    shoe_type = estimate_shoe_type(f"{title} {subtitle}")
    if shoe_type is None:
        return None
    brand, name = _brand_and_name(title)
    colors = item.get("displayColors") or {}
    simple = colors.get("simpleColor") or {}
    hex_color = f"#{simple.get('hex')}" if re.fullmatch(r"[0-9A-Fa-f]{6}", str(simple.get("hex") or "")) else None
    description = _clean(colors.get("colorDescription") or item.get("colorDescription"))
    label = _clean(simple.get("label")) or description
    if not url.startswith(BASE + "/"):
        url = f"{BASE}/fr/t/x/{code}"
    return ShopProduct(
        store="nike",
        product_ref=f"nike:{code}",
        name=name,
        price_cents=price,
        url=url,
        store_color=description[:60],
        section=section,
        type=shoe_type,
        category="calzado",
        # El color con nombre sencillo («Noir») y su tono: si la palabra es dudosa, manda el tono.
        color=estimate_color(label, hex_color),
        pattern=estimate_pattern(title),
        style=estimate_style(f"{title} {subtitle}", shoe_type),
        season=estimate_season(title, shoe_type),
        details=f"{brand} {name} {subtitle}".strip().lower(),
        brand=brand_name(brand),
        store_data={"code": code, "group": str(item.get("groupKey") or "") or None, "url": url, "hex": hex_color},
    )


def parse_wall(groupings: list, section: str) -> list[ShopProduct]:
    """De `productGroupings` (de la página o de la API que pide al desplazarse) a productos."""
    products: list[ShopProduct] = []
    refs: set[str] = set()
    for group in groupings or []:
        for item in (group or {}).get("products") or []:
            product = make_product(item, section)
            if product and product.product_ref not in refs:
                refs.add(product.product_ref)
                products.append(product)
    return products


def _photos(images: list) -> list[str]:
    urls = []
    for card in images or []:
        if not isinstance(card, dict) or card.get("cardType") not in (None, "image"):
            continue
        square = ((card.get("properties") or {}).get("squarish") or {}).get("url")
        if isinstance(square, str) and square.startswith("https://"):
            urls.append(square)
    order = [i for i in PHOTO_ORDER if i < len(urls)]
    if len(order) < 3:  # pocas fotos: las que haya, menos la suela si se puede
        order += [i for i in range(len(urls)) if i not in order and i != 1] + ([1] if len(urls) > 1 else [])
    return [urls[i] for i in dict.fromkeys(order)][:MAX_PHOTOS]


def parse_product_page(data: dict) -> tuple[dict, ShopDetail] | None:
    """De la ficha a (el producto como en el listado, su detalle). None si no es una ficha."""
    props = (data.get("props") or {}).get("pageProps") or {}
    selected = props.get("selectedProduct")
    if not isinstance(selected, dict) or not selected.get("styleColor"):
        return None
    info = selected.get("productInfo") or {}
    status = str(selected.get("statusModifier") or "")
    code = str(selected["styleColor"])
    siblings = []
    for other in props.get("colorwayImages") or []:
        other_code = str((other or {}).get("styleColor") or "")
        if not other_code or any(s["product_ref"] == f"nike:{other_code}" for s in siblings):
            continue
        url = str(other.get("pdpUrl") or f"{BASE}/fr/t/x/{other_code}")
        siblings.append({
            "product_ref": f"nike:{other_code}", "name": _clean(other.get("colorDescription")), "hex": None,
            "url": url, "store_data": {"code": other_code, "group": selected.get("groupKey"), "url": url},
        })
    if siblings and not any(s["product_ref"] == f"nike:{code}" for s in siblings):
        url = str(selected.get("pdpUrl") or f"{BASE}/fr/t/x/{code}")
        siblings.append({
            "product_ref": f"nike:{code}", "name": _clean(selected.get("colorDescription")), "hex": None,
            "url": url, "store_data": {"code": code, "group": selected.get("groupKey"), "url": url},
        })
    brands = (selected.get("taxonomyLabels") or {}).get("Brand") or []
    item = {
        "productCode": code, "productType": selected.get("productType"), "groupKey": selected.get("groupKey"),
        "copy": {"title": info.get("title"), "subTitle": info.get("subtitle")}, "prices": selected.get("prices"),
        "pdpUrl": {"url": selected.get("pdpUrl")} if isinstance(selected.get("pdpUrl"), str) else selected.get("pdpUrl"),
        "displayColors": {"colorDescription": selected.get("colorDescription")},
        "brand": brands[0] if brands else None,
    }
    detail = ShopDetail(
        price_cents=_cents((selected.get("prices") or {}).get("currentPrice")),
        sizes=[],  # la página no dice qué tallas quedan: sin tallas (ver arriba)
        photo_urls=_photos(selected.get("contentImages") or []),
        description=_clean(info.get("productDescription")),
        siblings=sorted(siblings, key=lambda s: s["product_ref"]) or None,
        store_color=_clean(selected.get("colorDescription"))[:60],
        stock_known=False,
        sold_out=bool(status) and not status.upper().startswith("BUYABLE"),
    )
    return item, detail


def reference(store_data: dict) -> str | None:
    """El código de fabricante, el de la caja y la etiqueta («HM6803-019»)."""
    return str(store_data.get("code") or "") or None


def parse_query(text: str) -> str:
    """El código de fabricante de lo que se busca: un enlace de producto de Nike o el código a secas.
    Lanza NotThisStore si no es nada que Nike sepa buscar (texto libre, enlaces de otras tiendas)."""
    text = " ".join((text or "").split())
    link = _LINK_TEXT.search(text)
    if link:
        url = link.group().rstrip(".,;)")
        parts = urlsplit(url if "://" in url else f"https://{url}")
        host = (parts.hostname or "").lower()
        if host != "nike.com" and not host.endswith(".nike.com"):
            raise NotThisStore("Todavía no sé buscar en esa tienda")
        last = parts.path.rstrip("/").rsplit("/", 1)[-1].upper()
        if "/t/" not in parts.path or not _CODE.fullmatch(last):
            raise SearchError("Ese enlace de Nike no es el de un producto: pega el de la página de la zapatilla")
        return last
    bare = re.sub(r"(?<!\w)(ref|r[ée]f(?:[ée]rence)?|code|style|article)(?!\w)\.?:?", " ", text, flags=re.IGNORECASE)
    code = bare.strip().upper().replace(" ", "")
    if _CODE.fullmatch(code):
        return code
    raise NotThisStore("Nike solo busca por referencia (tipo HM6803-019) o por enlace de producto")


class NikeConnector:
    key = "nike"
    name = "Nike"
    needs_browser = False  # True si deja de responder a un cliente normal: ver fetch.read_html
    heavy = False
    # No se sabe qué día saca novedades: los jueves (reparto de noches, ver shops/__init__.py).
    refresh_weekday = 3
    refresh_after_release = False
    language = "fr"
    categories = {slug: label for slug, (label, _path) in CATEGORIES.items()}
    section_types = {slug: "zapatillas" for slug in CATEGORIES}

    def __init__(self, pause: float | None = None):
        self.fetcher = Fetcher("nike", pause=max(config.SHOP_PAUSE_SECONDS, 3.0) if pause is None else pause,
                               timeout=config.SHOP_TIMEOUT_SECONDS, accept_language="fr-FR,fr;q=0.9")

    def _page(self, url: str) -> dict | None:
        status, text = read_html(self, url)
        if status in (404, 410):
            return None
        if status != 200:
            raise ShopError(f"HTTP {status}")
        return next_data(text)

    def list_category(self, slug: str) -> list[ShopProduct]:
        """La sección entera, de lo más nuevo a lo más viejo: la primera página y luego las que pide la
        propia web al desplazarse, hasta que no hay más (o el tope). Si una siguiente falla, `crawl.Partial`."""
        _label, path = CATEGORIES[slug]
        products: list[ShopProduct] = []
        refs: set[str] = set()

        def add(found: list[ShopProduct]) -> int:
            before = len(products)
            for product in found:
                if product.product_ref not in refs:
                    refs.add(product.product_ref)
                    products.append(product)
            return len(products) - before

        crawl.before_page()
        data = self._page(f"{BASE}{path}?{SORT}")
        if data is None:
            raise ShopError("HTTP 404")
        first = wall(data)
        pages = (first.get("pageData") or {})
        crawl.section_total(pages.get("totalPages") if isinstance(pages.get("totalPages"), int) else None)
        crawl.page_read(add(parse_wall(first.get("productGroupings"), slug)))
        following = pages.get("next")
        try:
            for _ in range(max(0, crawl.max_pages(self.key) - 1)):
                if not following or len(products) >= crawl.max_products(self.key):
                    break
                if not str(following).startswith("/discover/"):
                    break  # no es la dirección de siempre: no se sigue a ciegas
                crawl.before_page()
                status, more = read_json(self, API + following)
                if status != 200 or not isinstance(more, dict):
                    raise ShopError(f"HTTP {status}")
                crawl.page_read(add(parse_wall(more.get("productGroupings"), slug)))
                following = (more.get("pages") or {}).get("next")
        except ShopError as exc:
            raise crawl.Partial(products, exc) from exc
        return products

    def detail(self, store_data: dict) -> ShopDetail | None:
        url = str(store_data.get("url") or "")
        code = str(store_data.get("code") or "")
        if not url.startswith(BASE + "/"):
            if not _CODE.fullmatch(code):
                return None
            url = f"{BASE}/fr/t/x/{code}"
        data = self._page(url)
        parsed = parse_product_page(data) if data else None
        return parsed[1] if parsed else None

    def reference(self, store_data: dict) -> str | None:
        return reference(store_data)

    def search(self, query: str, limit: int = 12) -> list[ShopProduct]:
        code = parse_query(query)
        data = self._page(f"{BASE}/fr/t/x/{code}")
        parsed = parse_product_page(data) if data else None
        if not parsed:
            raise SearchError(f"No he encontrado nada en Nike con la referencia {code}")
        item, _detail = parsed
        product = make_product(item, "")
        if product is None:
            raise SearchError("Eso no son unas zapatillas que quepan en el armario")
        return [product][:max(1, min(limit, SEARCH_RESULTS))]

    def download(self, url: str) -> bytes:
        page = self.fetcher.get(url, accept=IMAGE, pause=0.5)
        if page.status != 200 or not page.content:
            raise ShopError(f"HTTP {page.status} al bajar la foto")
        return page.content
