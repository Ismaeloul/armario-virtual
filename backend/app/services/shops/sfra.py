"""Base común de Jules y Bonobo: tiendas de Salesforce Commerce Cloud (SFRA, la misma plataforma que
Courir) que, a diferencia de Courir, solo se dejan leer CON NAVEGADOR (browser.py): a un cliente normal su
Cloudflare le responde 403 «Just a moment…»; a un Chromium de serie con su ventana, no.

Cómo se lee (investigado el 18-11-2026):

- Se abre una página de la tienda (la de la sección) y, desde dentro (mismo origen, como hace la propia
  web con su botón «Afficher plus»), se pide el trozo de rejilla de `Search-UpdateGrid` (HTML) página a
  página hasta el final de la sección. De cada producto: su número (`pid`, modelo + color), nombre, precio
  y lo que haga falta para su ficha. Cada tienda pinta sus fichas a su manera: `parse_grid` es suyo.
- Ficha: `Product-Variation?pid=<pid>` (JSON), pedida igual desde dentro de la página: precio, tallas
  (`selectable` = quedan), color, composición, fotos y otros colores.
- Fotos: una sola sin modelo, la de delante (Jules `_V11`, Bonobo `vue3`). Si un color no la tiene, la
  primera con modelo, y se apunta (`model_photo`).
- Sin buscador: el navegador no se abre dentro de una petición HTTP; a un enlace de estas tiendas se le
  explica. Elegir otro color tampoco puede abrirlo: se enseñan apagados, con su enlace (`prepared_colors`).
"""
import html
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from ... import catalog, config
from . import browser, crawl
from .base import NeedsBrowser, NotThisStore, SearchError, ShopDetail, ShopError, ShopProduct, old_price
from .estimate import estimate_color, estimate_pattern, estimate_season, estimate_style, estimate_type
from .fetch import IMAGE, Fetcher

_TAGS = re.compile(r"<[^>]+>")
_LINK = re.compile(r"(?:https?://|www\.)\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}/\S*", re.IGNORECASE)
_TILE = re.compile(r'<div class="product" data-pid="(\d{6,20})"')


@dataclass(frozen=True)
class SfraSite:
    key: str
    name: str
    origin: str  # «https://www.jules.com»
    site_id: str  # «Sites-Jules-SFRA-Site»: va en las direcciones de `demandware.store`
    home: str  # una página cualquiera de la tienda, para abrir antes de pedir nada desde dentro
    # slug -> (nombre para el usuario, ruta de la sección, cgid, tipo por defecto o None)
    categories: dict = field(default_factory=dict)
    covered_by: dict = field(default_factory=dict)
    page_size: int = 32
    paging: str = "start"  # «start» (start=0, 32, 64…) o «page» (page=1, 2, 3…)
    locale: str = "fr_FR"

    @property
    def pipeline(self) -> str:
        return f"{self.origin}/on/demandware.store/{self.site_id}/{self.locale}"

    def grid_url(self, cgid: str, index: int) -> str:
        """La página `index` (desde 0) de una sección, como la pide el botón de la web."""
        if self.paging == "page":
            return f"{self.pipeline}/Search-UpdateGrid?cgid={cgid}&page={index + 1}"
        return f"{self.pipeline}/Search-UpdateGrid?cgid={cgid}&start={index * self.page_size}&sz={self.page_size}"

    def variation_url(self, pid: str) -> str:
        return f"{self.pipeline}/Product-Variation?pid={pid}"


def text_of(fragment: str) -> str:
    """El texto de un trozo de HTML, en una línea."""
    return " ".join(html.unescape(_TAGS.sub(" ", fragment or "")).split())


def cents(value) -> int | None:
    try:
        price = round(float(str(value).replace(",", ".")) * 100)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


def list_price(product: dict) -> int | None:
    """El precio de antes de la rebaja en la ficha (`Product-Variation`): `price.list` junto a `price.sales`
    (el de ahora). Visto en Bonobo (59,99 € antes, 41,99 € ahora, con `percent`); en Jules el campo llega
    a null cuando no hay rebaja. La rejilla no lo dice."""
    price = (product or {}).get("price") or {}
    return old_price(cents((price.get("sales") or {}).get("value")), cents((price.get("list") or {}).get("value")))


def tiles(page: str) -> list[tuple[str, str]]:
    """(pid, su trozo de HTML) de cada producto de la rejilla, en orden y sin repetir."""
    found: list[tuple[str, str]] = []
    matches = list(_TILE.finditer(page or ""))
    seen: set[str] = set()
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(page)
        if match.group(1) not in seen:
            seen.add(match.group(1))
            found.append((match.group(1), page[match.start():end]))
    return found


def make_product(site: SfraSite, *, pid: str, name: str, price: int | None, url: str, section: str,
                 store_color: str = "", hex_color: str | None = None, extra: dict | None = None,
                 default_type: str | None = None) -> ShopProduct | None:
    """Un producto de la rejilla. None si no cabe en el armario."""
    name = " ".join((name or "").split())
    garment_type = estimate_type(name, default_type)
    if garment_type == "chaqueta" and default_type == "sudadera":
        garment_type = "sudadera"  # «Veste zippée sherpa» en Sudaderas: una sudadera con cremallera
    if not pid or not name or price is None or garment_type is None:
        return None
    return ShopProduct(
        store=site.key,
        product_ref=f"{site.key}:{pid}",
        name=name,
        price_cents=price,
        url=url,
        store_color=store_color[:60],
        section=section,
        type=garment_type,
        category=catalog.category_of(garment_type),
        color=estimate_color(store_color, hex_color),
        pattern=estimate_pattern(f"{name} {store_color}"),
        style=estimate_style(name, garment_type),
        season=estimate_season(name, garment_type),
        details=name.lower(),
        store_data={"pid": pid, "url": url, **(extra or {})},
    )


def sizes_of(product: dict) -> list[dict]:
    """Las tallas de la ficha (`variationAttributes` «size»): `selectable` = quedan."""
    sizes, seen = [], set()
    for attribute in product.get("variationAttributes") or []:
        if (attribute or {}).get("attributeId") != "size" and (attribute or {}).get("id") != "size":
            continue
        for value in attribute.get("values") or []:
            name = " ".join(str((value or {}).get("displayValue") or "").split())
            if name and name not in seen:
                seen.add(name)
                sizes.append({"name": name, "in_stock": bool(value.get("selectable"))})
    return sizes


def color_values(product: dict) -> list[dict]:
    for attribute in product.get("variationAttributes") or []:
        if (attribute or {}).get("attributeId") == "color" or (attribute or {}).get("id") == "color":
            return [v for v in attribute.get("values") or [] if isinstance(v, dict)]
    return []


class SfraConnector:
    """Jules y Bonobo: misma plataforma, distinta tienda (`site`). Cada una lee su rejilla y elige sus fotos."""

    needs_browser = True
    heavy = True  # muchas secciones y una ficha por propuesta: de estas, como mucho dos por noche
    refresh_after_release = False
    language = "fr"
    # Elegir otro color no puede abrir el navegador: se enseñan apagados, con su enlace a la tienda.
    prepared_colors = True

    def __init__(self, site: SfraSite, refresh_weekday: int):
        self.site = site
        self.key = site.key
        self.name = site.name
        self.refresh_weekday = refresh_weekday
        self.categories = {slug: entry[0] for slug, entry in site.categories.items()}
        self.section_types = {slug: entry[3] for slug, entry in site.categories.items()}
        self.covered_by = site.covered_by
        self.fetcher = Fetcher(site.key, pause=2.0, timeout=config.SHOP_TIMEOUT_SECONDS, accept_language="fr-FR,fr;q=0.9")

    # --- lo que cada tienda pinta a su manera

    def parse_grid(self, page: str, section: str) -> list[ShopProduct]:
        raise NotImplementedError

    def parse_variation(self, data: dict, store_data: dict) -> ShopDetail | None:
        raise NotImplementedError

    # --- por dentro

    def _session(self, path: str | None = None):
        """La sesión del navegador con una página de la tienda abierta (para pedir desde dentro)."""
        session = browser.require(self.key)
        if not session.host().startswith(self.site.origin + "/"):
            status, _page = session.page_html(self.key, self.site.origin + (path or self.site.home))
            if status is not None and status >= 400:
                raise ShopError(f"HTTP {status}")
        return session

    # --- la interfaz de los conectores

    def list_category(self, slug: str) -> list[ShopProduct]:
        """La sección entera, página a página de la rejilla, hasta la que trae menos (o el tope). Si una
        siguiente falla o la tienda bloquea a mitad, `crawl.Partial` con lo leído."""
        _label, path, cgid, _default = self.site.categories[slug]
        products: list[ShopProduct] = []
        refs: set[str] = set()
        try:
            crawl.before_page()
            session = self._session(path)
            for index in range(max(1, crawl.max_pages(self.key))):
                if index:
                    crawl.before_page()
                status, page = session.fetch_text(self.key, self.site.grid_url(cgid, index))
                if status != 200:
                    raise ShopError(f"HTTP {status}")
                found = tiles(page)
                if index == 0 and not found:
                    raise ShopError("la respuesta no era la esperada (sin productos)")
                before = len(products)
                for product in self.parse_grid(page, slug):
                    if product.product_ref not in refs:
                        refs.add(product.product_ref)
                        products.append(product)
                crawl.page_read(len(products) - before)
                if len(found) < self.site.page_size or len(products) >= crawl.max_products(self.key):
                    break  # no hay más páginas (o el tope de seguridad)
        except ShopError as exc:
            if not products:
                raise
            raise crawl.Partial(products, exc) from exc
        return products

    def detail(self, store_data: dict) -> ShopDetail | None:
        pid = str(store_data.get("pid") or "")
        if not pid.isdigit():
            return None
        if not browser.active():  # una petición HTTP normal (elegir otro color): aquí no se abre
            raise NeedsBrowser(f"{self.name} solo se lee con navegador, en las consultas en segundo plano: "
                               "ese color no se puede traer ahora")
        status, data = self._session().fetch_json(self.key, self.site.variation_url(pid))
        if status in (400, 404, 410) or (status == 200 and not isinstance(data, dict)):
            return None
        if status != 200:
            raise ShopError(f"HTTP {status}")
        product = data.get("product")
        if not isinstance(product, dict) or not product.get("id"):
            return None
        return self.parse_variation(product, store_data)

    def reference(self, store_data: dict) -> str | None:
        """El número del producto (modelo + color), el que sale en su enlace."""
        return str(store_data.get("pid") or "") or None

    def search(self, query: str, limit: int = 12) -> list[ShopProduct]:
        """Sin buscador: el navegador no se abre dentro de una petición HTTP."""
        link = _LINK.search(" ".join((query or "").split()))
        if link:
            url = link.group().rstrip(".,;)")
            host = (urlsplit(url if "://" in url else f"https://{url}").hostname or "").lower()
            domain = urlsplit(self.site.origin).hostname.removeprefix("www.")
            if host == domain or host.endswith("." + domain):
                raise SearchError(
                    f"{self.name} solo se lee con navegador en las consultas semanales: el buscador no la abre. "
                    "Actívala en Tiendas y saldrá en Descubrir si está en sus secciones."
                )
        raise NotThisStore("Todavía no sé buscar en esa tienda")

    def download(self, url: str) -> bytes:
        page = self.fetcher.get(url, accept=IMAGE)
        if page.status != 200 or not page.content:
            raise ShopError(f"HTTP {page.status} al bajar la foto")
        return page.content
