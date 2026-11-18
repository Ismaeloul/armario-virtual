"""Conector de Nike (nike.com/fr): SOLO zapatillas de hombre.

Se lee CON NAVEGADOR (browser.py), como Uniqlo o Mango. Hasta el 18-11-2026 se leía sin él (httpx): la
primera página del listado y, para las siguientes, la dirección `pageData.next` de api.nike.com. Esa
petición pasó a responder HTTP 400 (en el PC y en el Umbrel) y solo se leía la primera página. No se ha
investigado por qué a base de peticiones: se abre la sección en el navegador de serie, como un usuario, y
se ESCUCHA lo que pide la propia página al bajar. Nada de cabeceras ni identificadores copiados de la web,
y nunca se pide a api.nike.com por nuestra cuenta.

- Listado: la página de la sección (`/fr/w/hommes-chaussures-nik1zy7ok?sortBy=newest`, lo más nuevo
  primero) trae en su `__NEXT_DATA__` los 24 primeros modelos (`Wall.productGroupings`, un producto por
  color, agrupados por modelo). Para los siguientes se baja la página hasta el final (`more`) y se oyen las
  respuestas que pide ella sola (`/discover/product_wall/…&anchor=24&count=24`: el mismo JSON, con su
  `pages.next`). Se sigue hasta que no hay `next` (~33 páginas) o los topes de crawl.py. Si con `next`
  pendiente la página ya no pide nada al bajar, la sección queda a medias (`crawl.Partial`).
- Lo que el listado ya dice de cada color se guarda (`snap`: su foto de producto y los otros colores del
  mismo modelo), y de día la ficha sale de ahí sin abrir el navegador (`cached_detail`): una sola foto (la
  lateral, la del listado), sin descripción. De noche, con el navegador abierto, se abre la ficha de
  verdad (más fotos y la descripción). Elegir otro color de día solo vale con los ya preparados
  (`prepared_colors`, como JD Sports).
- Ficha: el `__NEXT_DATA__` de la página del producto (`selectedProduct`): precio, descripción, fotos
  (`contentImages`: en calzado, todas sin modelo) y los otros colores (`colorwayImages`).
- Tallas: la página no dice cuáles quedan (las enseña todas como «ACTIVE»; el stock lo pide aparte a
  una API interna que NO se llama, por decisión firme). Así que la zapatilla sale SIN tallas y cuenta
  como disponible mientras la tienda la venda (`statusModifier` «BUYABLE…»).
- Referencia: el código de fabricante, el de la caja y la web («HM6803-019»).
- Buscador: el navegador no se abre dentro de una petición HTTP, así que solo encuentra lo ya leído del
  listado (lo busca shopping en lo guardado, por código o enlace). Con un código o un enlace de Nike que
  no esté ahí, se explica. Sin texto libre: el buscador de la web está prohibido en su robots.txt.
- Las fotos, de su CDN (static.nike.com), que responde a un cliente normal.
"""
import json
import re
from urllib.parse import urlsplit

from ... import config
from . import browser, crawl
from .base import NeedsBrowser, NotThisStore, SearchError, ShopDetail, ShopError, ShopProduct, old_price
from .estimate import brand_name, estimate_color, estimate_pattern, estimate_season, estimate_shoe_type
from .estimate import estimate_style
from .fetch import IMAGE, Fetcher, read_html

BASE = "https://www.nike.com"
SORT = "sortBy=newest"
WALL_PATH = "/discover/product_wall/"  # lo que pide la página al bajar para traer más modelos
MORE_WAIT = 15.0  # lo que se espera a que la página pida los siguientes tras bajar
MAX_COLORS = 12  # otros colores del mismo modelo que se guardan del listado
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
    prices = item.get("prices") or {}
    price = _cents(prices.get("currentPrice"))
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
        # Rebajada: `initialPrice` (el de antes) mayor que `currentPrice` (con `discountPercentage`).
        old_price_cents=old_price(price, _cents(prices.get("initialPrice"))),
        old_price_known=True,
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


def _listing_photo(item: dict) -> str | None:
    """La foto de producto que enseña el listado (la lateral, sin modelo, en cuadrado)."""
    url = (item.get("colorwayImages") or {}).get("squarishURL")
    return url if isinstance(url, str) and url.startswith("https://static.nike.com/") else None


def parse_wall(groupings: list, section: str) -> list[ShopProduct]:
    """De `productGroupings` (de la página o de lo que pide al bajar) a productos. Cada uno guarda lo que el
    listado ya dice para su ficha (`snap`): su foto y los demás colores del mismo modelo que salen ahí."""
    products: list[ShopProduct] = []
    refs: set[str] = set()
    for group in groupings or []:
        found = []
        for item in (group or {}).get("products") or []:
            product = make_product(item, section)
            if product and product.product_ref not in refs:
                refs.add(product.product_ref)
                found.append((product, _listing_photo(item)))
        colors = [{
            "code": p.store_data["code"], "name": p.store_color, "hex": p.store_data.get("hex"), "url": p.url,
        } for p, photo in found if photo][:MAX_COLORS]
        for product, photo in found:
            if photo:
                product.store_data["snap"] = {"photo": photo, "colors": colors}
            products.append(product)
    return products


def detail_from_listing(store_data: dict) -> ShopDetail | None:
    """La ficha a partir de lo que guardó el listado (`snap`), sin abrir la página del producto: la foto del
    listado y los otros colores del mismo modelo que salían ahí. Sin tallas (como la ficha de verdad) ni
    descripción. None si el listado no dejó lo necesario."""
    snap = store_data.get("snap")
    code = str(store_data.get("code") or "")
    if not isinstance(snap, dict) or not _CODE.fullmatch(code):
        return None
    photo = snap.get("photo")
    if not isinstance(photo, str) or not photo.startswith("https://static.nike.com/"):
        return None
    siblings, own = [], None
    for color in snap.get("colors") or []:
        other = str((color or {}).get("code") or "")
        if not _CODE.fullmatch(other) or any(s["product_ref"] == f"nike:{other}" for s in siblings):
            continue
        url = str(color.get("url") or "")
        if not url.startswith(BASE + "/"):
            url = f"{BASE}/fr/t/x/{other}"
        hex_color = color.get("hex") if re.fullmatch(r"#[0-9A-Fa-f]{6}", str(color.get("hex") or "")) else None
        siblings.append({
            "product_ref": f"nike:{other}", "name": _clean(color.get("name")), "hex": hex_color, "url": url,
            "store_data": {"code": other, "group": store_data.get("group"), "url": url, "hex": hex_color},
        })
        if other == code:
            own = siblings[-1]
    return ShopDetail(
        price_cents=None,  # el del listado ya está en el producto
        sizes=[],  # la tienda no dice qué tallas quedan (ver arriba)
        photo_urls=[photo],
        siblings=sorted(siblings, key=lambda s: s["product_ref"]) if own and len(siblings) > 1 else None,
        store_color=own["name"] if own else "",
        stock_known=False,  # salía en el listado: la tienda la vende
    )


def is_wall(url: str) -> bool:
    """¿Es la petición con la que la página trae más modelos al bajar?"""
    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    return (host == "nike.com" or host.endswith(".nike.com")) and WALL_PATH in parts.path


def anchor_of(url: str) -> int:
    """Desde qué producto trae esa petición (`anchor=24`); -1 si no lo dice."""
    match = re.search(r"[?&]anchor=(\d+)", url or "")
    return int(match.group(1)) if match else -1


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
    prices = selected.get("prices") or {}
    detail = ShopDetail(
        price_cents=_cents(prices.get("currentPrice")),
        old_price_cents=old_price(_cents(prices.get("currentPrice")), _cents(prices.get("initialPrice"))),
        old_price_known=True,
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
    needs_browser = True
    # Con navegador, pero una sola sección de zapatillas: como JD Sports, Snipes y size?, no cuenta como
    # «pesada» en el reparto de noches (ver shops/__init__.py).
    heavy = False
    # Elegir otro color de día no puede abrir el navegador: solo los ya preparados (ver shopping.prepare_colors).
    prepared_colors = True
    # No se sabe qué día saca novedades: los jueves (reparto de noches, ver shops/__init__.py).
    refresh_weekday = 3
    refresh_after_release = False
    language = "fr"
    categories = {slug: label for slug, (label, _path) in CATEGORIES.items()}
    section_types = {slug: "zapatillas" for slug in CATEGORIES}

    def __init__(self, pause: float | None = None):
        # Solo para las fotos, de su CDN: las páginas de la tienda van por el navegador (fetch.read_html).
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
        """La sección entera, de lo más nuevo a lo más viejo: la página abierta en el navegador y luego lo que
        ella misma pide al bajar hasta el final, hasta que no hay más (o el tope). Si una siguiente falla o la
        página deja de pedir más con más por leer, `crawl.Partial` con lo leído."""
        _label, path = CATEGORIES[slug]
        session = browser.require(self.key)
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
        status, text = session.page_html(self.key, f"{BASE}{path}?{SORT}")
        if status != 200 or not text:
            raise ShopError(f"HTTP {status}")
        first = wall(next_data(text))
        pages = (first.get("pageData") or {})
        crawl.section_total(pages.get("totalPages") if isinstance(pages.get("totalPages"), int) else None)
        crawl.page_read(add(parse_wall(first.get("productGroupings"), slug)))
        following = pages.get("next")
        anchors = {0}  # lo que ya se ha leído (la página trae desde el 0)
        # Una «página» es una tanda de 24 modelos (lo que cuenta `totalPages`). Una bajada hasta el final
        # suele traer varias (comprobado: tres), porque la página pide la siguiente cada vez que se llega abajo.
        read = 1
        try:
            while following and read < crawl.max_pages(self.key) and len(products) < crawl.max_products(self.key):
                crawl.before_page()
                responses = session.more(self.key, want=is_wall, wait=MORE_WAIT,
                                         ready=lambda urls: any(anchor_of(u) not in anchors for u in urls))
                fresh = sorted((r for r in responses if anchor_of(r.url) not in anchors), key=lambda r: anchor_of(r.url))
                if not fresh:
                    raise ShopError("la página no pidió más productos al bajar")
                for response in fresh:
                    anchors.add(anchor_of(response.url))
                    if response.status != 200 or not isinstance(response.data, dict):
                        raise ShopError(f"HTTP {response.status}")
                    crawl.page_read(add(parse_wall(response.data.get("productGroupings"), slug)))
                    read += 1
                    following = (response.data.get("pages") or {}).get("next")
        except ShopError as exc:
            raise crawl.Partial(products, exc) from exc
        return products

    def cached_detail(self, store_data: dict) -> ShopDetail | None:
        """De día (sin navegador abierto), la ficha sale de lo que guardó el listado. Con el navegador abierto
        (de noche, «Ver más»), None: se abre la ficha de verdad, con más fotos y la descripción."""
        if browser.active():
            return None
        return detail_from_listing(store_data)

    def detail(self, store_data: dict) -> ShopDetail | None:
        url = str(store_data.get("url") or "")
        code = str(store_data.get("code") or "")
        if not url.startswith(BASE + "/"):
            if not _CODE.fullmatch(code):
                return None
            url = f"{BASE}/fr/t/x/{code}"
        if not browser.active():  # una petición HTTP normal (elegir otro color): aquí no se abre
            raise NeedsBrowser(f"{self.name} solo se lee con navegador, en las consultas en segundo plano: "
                               "ese color no se puede traer ahora")
        data = self._page(url)
        parsed = parse_product_page(data) if data else None
        return parsed[1] if parsed else None

    def reference(self, store_data: dict) -> str | None:
        return reference(store_data)

    def maker_code(self, store_data: dict) -> str | None:
        return reference(store_data)

    def search(self, query: str, limit: int = 12) -> list[ShopProduct]:
        """Lo ya leído del listado lo encuentra shopping en lo guardado, antes de llegar aquí. Aquí solo
        llega lo que no está: dentro de una petición HTTP el navegador no se abre, y se explica."""
        code = parse_query(query)  # NotThisStore si no es de Nike; SearchError si el enlace no es de un producto
        if not browser.active():
            raise SearchError(
                f"{self.name} solo se lee con navegador en las consultas semanales: la referencia {code} no está "
                "en lo leído de su listado. Actívala en Tiendas y saldrá en Descubrir si está entre sus novedades."
            )
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
