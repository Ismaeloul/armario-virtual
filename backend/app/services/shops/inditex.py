"""Base común de Pull&Bear y Bershka (Francia): la misma plataforma de Inditex que Zara, pero detrás
de un antibots que solo deja pasar a un navegador de verdad con su ventana (ver browser.py).

Cómo se lee (investigado el 18-11-2026):

- Se abre la página de la sección con Chromium y se ESCUCHAN las respuestas JSON que la propia web
  pide a `itxrest`: la de la categoría (`.../category/<id>/product?...`, con los ids de sus productos
  en el orden de la tienda) y la primera tanda de fichas (`.../productsArray?productIds=...`). Las
  fichas que faltan hasta PER_CATEGORY se piden desde dentro de la página (mismo origen), con la
  misma dirección que usa la web. No se lee nada de lo que pinta la página.
- `productsArray` trae ya la ficha entera de cada producto: todos sus colores, tallas, precio,
  composición y fotos. Así que el listado deja guardada una «instantánea» compacta del producto en
  `store_data` (`snap`), y la ficha (`detail`) sale de ahí sin volver a la tienda: lo nuevo de la
  semana, «Ver más» del mismo día y elegir otro color (que va en una petición HTTP normal, donde el
  navegador no se abre nunca). Si la instantánea es vieja y hay navegador (la consulta semanal de los
  «me gusta», un «Ver más» de otro día), se pide la ficha a la tienda.
- Fotos: las de producto sin modelo tienen nombre propio en cada tienda y cambian en el calzado
  (`a6m` delante y `a20m` detrás en la ropa de Pull&Bear; `a4o` y `b1` en Bershka; ver cada conector). Si un color solo tiene fotos con modelo, se usa la
  primera y se apunta (`model_photo`). Las fotos salen de la CDN, que sí responde a un cliente normal.
- Buscador: no. Abrir el navegador dentro de una petición HTTP no se hace; un enlace de estas tiendas
  responde con un mensaje que lo explica.
"""
import re
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit

from ... import catalog, config
from . import browser
from .base import NeedsBrowser, NotThisStore, SearchError, ShopDetail, ShopError, ShopProduct
from .estimate import estimate_color, estimate_pattern, estimate_season, estimate_style, estimate_type
from .estimate import sentence_case
from .fetch import IMAGE, Fetcher

PER_CATEGORY = 40  # productos que se leen de cada sección: los primeros, en el orden de la tienda
BATCH = 20  # fichas por petición, como las pide la web
SNAPSHOT_HOURS = 24  # una instantánea más vieja se pide otra vez (si hay navegador)
PHOTO_WIDTH = 1280
MAX_PHOTOS = 3
DESCRIPTION_MAX = 400
COMPOSITION_MAX = 300
_LINK = re.compile(r"(?:https?://|www\.)\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}/\S*", re.IGNORECASE)
_STORE_URL = re.compile(r"/catalog/store/(\d+)/(\d+)/")


@dataclass(frozen=True)
class InditexSite:
    key: str
    name: str
    origin: str  # «https://www.pullandbear.com»
    path: str  # país e idioma en las direcciones: «/fr»
    store_id: int  # la tienda de Francia en `itxrest` (sale en las peticiones de la propia web)
    catalog_id: int  # el catálogo: se aprende de las peticiones; este es el visto el 18-11-2026
    media: str  # dónde están las fotos: «https://static.pullandbear.net/assets/public»
    # Las fotos de producto sin modelo, por su nombre en la tienda: una tupla por vista (delante,
    # detrás…), cada una con sus nombres por orden de preferencia. La primera vista es obligatoria.
    views: tuple[tuple[str, ...], ...]
    shoe_views: tuple[tuple[str, ...], ...]  # en calzado: lateral, tres cuartos, otra vista
    color_param: str  # el color en el enlace del producto: «cS» (Pull&Bear) o «colorId» (Bershka)
    bundle_param: str | None  # Pull&Bear lleva además el id del producto en `pelement`
    # slug de la sección -> (nombre para el usuario, ruta después de `path`, tipo por defecto)
    categories: dict = field(default_factory=dict)

    @property
    def base(self) -> str:
        return self.origin + self.path


# ---------- Lo que se lee del JSON


def _summary(product: dict) -> dict | None:
    """El producto de verdad: en el listado cada uno va envuelto en un «bundle» (con otro id); la
    ficha suelta (`/detail`) ya es el producto."""
    if not isinstance(product, dict):
        return None
    summaries = product.get("bundleProductSummaries") or []
    summary = summaries[0] if summaries and isinstance(summaries[0], dict) else product
    colors = (summary.get("detail") or {}).get("colors")
    return summary if isinstance(colors, list) and colors else None


def _price(color: dict) -> int | None:
    prices = []
    for size in color.get("sizes") or []:
        try:
            prices.append(int(str((size or {}).get("price") or "").strip()))
        except ValueError:
            continue
    prices = [p for p in prices if p > 0]
    return min(prices) if prices else None


def _sizes(color: dict) -> list[list]:
    """[[nombre, quedan]] en el orden de la tienda. Una talla puede venir repetida (Bershka trae una
    entrada por variante): queda si alguna se enseña como disponible."""
    sizes: dict[str, bool] = {}
    for size in color.get("sizes") or []:
        name = str((size or {}).get("name") or "").strip()
        if not name:
            continue
        shown = str(size.get("visibilityValue") or "SHOW").upper() == "SHOW" and size.get("isBuyable") is not False
        sizes[name] = sizes.get(name, False) or shown
    return [[name, stock] for name, stock in sizes.items()]


def _photos(detail: dict, color_id: str, site: InditexSite, shoes: bool = False) -> tuple[list[str], bool]:
    """Las fotos de producto de un color (rutas relativas a `site.media`), en el orden de la app. Si no
    hay ninguna sin modelo, la primera foto con modelo y True."""
    medias: list[dict] = []
    for xmedia in detail.get("xmedia") or []:
        if str((xmedia or {}).get("colorCode")) != color_id:
            continue
        items = [i for i in xmedia.get("xmediaItems") or [] if isinstance(i, dict)]
        items.sort(key=lambda i: i.get("set") != 0)  # el juego 0 es el de la ficha
        medias = [m for m in (items[0].get("medias") or []) if isinstance(m, dict)] if items else []
        break
    by_name: dict[str, str] = {}
    for media in medias:
        info = media.get("extraInfo") or {}
        name = str(info.get("originalName") or "").lower()
        url = str(media.get("url") or info.get("deliveryUrl") or "")
        if name and url.startswith(site.media + "/"):
            by_name.setdefault(name, url[len(site.media):])
    views = [next((by_name[n] for n in names if n in by_name), None) for names in (site.shoe_views if shoes else site.views)]
    if views and views[0]:
        return [p for p in views if p][:MAX_PHOTOS], False
    # Solo con modelo: la primera foto de verdad (la `r1` es una miniatura de relleno de pocos bytes).
    for media in medias:
        name = str((media.get("extraInfo") or {}).get("originalName") or "").lower()
        if media.get("clazz", 1) == 1 and name and not name.startswith("r") and name in by_name:
            return [by_name[name]], True
    return [], False


def _composition(detail: dict, color: dict) -> str:
    """«Extérieur: 65% coton, 35% polyester · Doublure: 100% coton»."""
    composition = color.get("compositionDetail") or detail.get("compositionDetail") or {}
    parts: list[str] = []
    for part in composition.get("parts") or []:
        if not isinstance(part, dict):
            continue
        components: list[str] = []
        for group in [part] + [area for area in part.get("areas") or [] if isinstance(area, dict)]:
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
    return " · ".join(parts)[:COMPOSITION_MAX]


def snapshot(product: dict, site: InditexSite, now: float | None = None) -> dict | None:
    """La instantánea compacta de un producto con todos sus colores: lo que hace falta para su ficha
    sin volver a la tienda. None si el JSON no es un producto."""
    summary = _summary(product)
    if summary is None:
        return None
    detail = summary.get("detail") or {}
    shoes = str(summary.get("productType") or product.get("productType") or "").lower() == "footwear"
    colors = []
    description = ""
    for color in detail.get("colors") or []:
        if not isinstance(color, dict) or color.get("id") in (None, ""):
            continue
        color_id = str(color["id"])
        photos, model = _photos(detail, color_id, site, shoes)
        colors.append({
            "id": color_id,
            "name": " ".join(str(color.get("name") or "").split()),
            "price": _price(color),
            "sizes": _sizes(color),
            "photos": photos,
            "model": model,
        })
        description = description or str(color.get("longDescription") or "")
    description = description or str(detail.get("longDescription") or detail.get("description") or "")
    first = next((c for c in detail.get("colors") or [] if isinstance(c, dict)), {})
    return {
        "at": int(now if now is not None else time.time()),
        "desc": " ".join(description.split())[:DESCRIPTION_MAX],
        "comp": _composition(detail, first),
        "colors": colors,
    }


def product_url(site: InditexSite, page: str, bundle: str, color: str) -> str:
    query = {site.color_param: color}
    if site.bundle_param:
        query[site.bundle_param] = bundle
    return f"{site.origin}{page}?{urlencode(query)}"


def _page(site: InditexSite, summary: dict, bundle: str, name: str) -> str:
    """La ruta de la página del producto. Pull&Bear: `/fr/<productUrl>`. Bershka: `/fr/<nombre>-c0p<id>.html`,
    con el nombre en minúsculas y guiones, como en sus propios enlaces."""
    if site.bundle_param:
        return f"{site.path}/{summary.get('productUrl') or 'p'}"
    words = re.sub(r"[^\w]+", "-", name.lower()).strip("-") or "p"
    return f"{site.path}/{quote(words)}-c0p{bundle}.html"


def reference(store_data: dict) -> str | None:
    """«3501/500/803»: modelo, calidad y color, como en la etiqueta y en la web."""
    ref = str(store_data.get("ref") or "").strip()
    color = str(store_data.get("color") or "").strip()
    if not re.fullmatch(r"\d{3,5}/\d{3}", ref):
        return None
    return f"{ref}/{color}" if re.fullmatch(r"\d{3}", color) else ref


def make_product(site: InditexSite, product: dict, section: str, default_type: str | None,
                 now: float | None = None) -> ShopProduct | None:
    """Un producto del listado, en el color con el que lo enseña la tienda. None si no cabe en el armario."""
    summary = _summary(product)
    if summary is None or str(summary.get("sectionNameEN") or "MEN").upper() not in ("MEN", "MAN", ""):
        return None
    detail = summary.get("detail") or {}
    color = next((c for c in detail.get("colors") or [] if isinstance(c, dict) and c.get("id") not in (None, "")), None)
    name = " ".join(str(summary.get("name") or product.get("name") or "").split())
    if color is None or not name:
        return None
    name = name if any(ch.islower() for ch in name) else sentence_case(name)
    family = f"{summary.get('familyName') or ''} {summary.get('subFamilyName') or ''}"
    # Sin tipo en el nombre, el de la sección; sin sección (otro color, una ficha suelta), el de la familia.
    garment_type = estimate_type(name, default_type or estimate_type(family))
    price = _price(color)
    if garment_type is None or price is None:
        return None
    summary_id, color_id = str(summary.get("id") or ""), str(color["id"])
    bundle = str(product.get("id") or summary_id)
    if not summary_id:
        return None
    page = _page(site, summary, bundle, name)
    store_color = " ".join(str(color.get("name") or "").split())
    details = name.lower()
    return ShopProduct(
        store=site.key,
        product_ref=f"{site.key}:{summary_id}-{color_id}",
        name=name,
        price_cents=price,
        url=product_url(site, page, bundle, color_id),
        store_color=store_color,
        section=section,
        type=garment_type,
        category=catalog.category_of(garment_type),
        color=estimate_color(store_color),
        pattern=estimate_pattern(name),
        style=estimate_style(name, garment_type),
        season=estimate_season(name, garment_type),
        details=details,
        store_data={
            "id": summary_id, "bundle": bundle, "color": color_id, "page": page,
            "ref": str((detail.get("displayReference") or "")).strip() or None,
            "snap": snapshot(product, site, now),
        },
    )


def parse_products(products: list, site: InditexSite, section: str, now: float | None = None) -> list[ShopProduct]:
    """De las fichas de `productsArray` a productos normalizados, sin repetir (el mismo producto
    puede salir envuelto en dos «bundles»)."""
    default_type = site.categories.get(section, (None, None, None))[2]
    found: list[ShopProduct] = []
    refs: set[str] = set()
    for product in products or []:
        item = make_product(site, product, section, default_type, now)
        if item and item.product_ref not in refs:
            refs.add(item.product_ref)
            found.append(item)
    return found


def category_ids(data: dict) -> list[str]:
    """Los ids de los productos de una categoría, en el orden de la tienda."""
    ids = data.get("sortedProductIds") or data.get("productIds") or []
    out: list[str] = []
    for value in ids:
        value = str(value)
        if value.isdigit() and value not in out:
            out.append(value)
    return out


def detail_from(site: InditexSite, store_data: dict, snap: dict | None = None) -> ShopDetail | None:
    """La ficha de un color a partir de la instantánea del producto. None si ese color ya no está."""
    snap = snap if snap is not None else store_data.get("snap")
    if not isinstance(snap, dict):
        return None
    colors = [c for c in snap.get("colors") or [] if isinstance(c, dict)]
    wanted = str(store_data.get("color") or "")
    color = next((c for c in colors if c.get("id") == wanted), None)
    if color is None:
        return None
    summary_id, bundle, page = str(store_data.get("id")), str(store_data.get("bundle") or store_data.get("id")), \
        str(store_data.get("page") or "")
    base = {"id": summary_id, "bundle": bundle, "page": page, "ref": store_data.get("ref"), "snap": snap}
    siblings = [
        {
            "product_ref": f"{site.key}:{summary_id}-{c['id']}",
            "name": c.get("name") or "",
            "hex": None,
            "price_cents": c.get("price"),
            "url": product_url(site, page, bundle, c["id"]),
            "store_data": {**base, "color": c["id"]},
        }
        for c in colors
        if c.get("photos")
    ]
    return ShopDetail(
        price_cents=color.get("price"),
        sizes=[{"name": name, "in_stock": bool(stock)} for name, stock in color.get("sizes") or []],
        photo_urls=[f"{site.media}{path}{'&' if '?' in path else '?'}w={PHOTO_WIDTH}" for path in color.get("photos") or []],
        description=snap.get("desc") or "",
        composition=snap.get("comp") or "",
        siblings=siblings,
        store_color=color.get("name") or "",
        store_data={"model_photo": True} if color.get("model") else {},
    )


def fresh(store_data: dict, now: float | None = None) -> bool:
    snap = store_data.get("snap")
    at = snap.get("at") if isinstance(snap, dict) else None
    return isinstance(at, (int, float)) and (now if now is not None else time.time()) - at < SNAPSHOT_HOURS * 3600


def with_ids(url: str, ids: list[str]) -> str:
    """La dirección de `productsArray` de la web con otros ids."""
    parts = urlsplit(url)
    query = [(k, v) for k, values in parse_qs(parts.query, keep_blank_values=True).items() for v in values]
    query = [(k, v) for k, v in query if k != "productIds"] + [("productIds", ",".join(ids))]
    return urlunsplit(parts._replace(query=urlencode(query, safe=",")))


def array_url(category_url: str) -> str:
    """Si la página no pidió fichas, la misma dirección que pide la web, sacada de la de la categoría."""
    parts = urlsplit(category_url)
    match = re.search(r"/category/(\d+)/product$", parts.path)
    if not match:
        raise ShopError("la respuesta no era la esperada (sin categoría)")
    path = parts.path[: match.start()] + "/productsArray"
    query = {k: v[0] for k, v in parse_qs(parts.query).items() if k in ("languageId", "appId", "locale")}
    return urlunsplit(parts._replace(path=path, query=urlencode({"categoryId": match.group(1), **query})))


# ---------- El conector


class InditexConnector:
    """Pull&Bear y Bershka: misma plataforma, distinta tienda (`site`)."""

    needs_browser = True
    refresh_after_release = False
    language = "fr"

    def __init__(self, site: InditexSite, refresh_weekday: int):
        self.site = site
        self.key = site.key
        self.name = site.name
        self.refresh_weekday = refresh_weekday
        self.categories = {slug: label for slug, (label, _path, _type) in site.categories.items()}
        self.catalog_id = site.catalog_id
        # Las fotos, de la CDN: un cliente normal, con su pausa corta.
        self.fetcher = Fetcher(site.key, pause=0.3, timeout=config.SHOP_TIMEOUT_SECONDS, accept_language="fr-FR,fr;q=0.9")

    # --- direcciones

    def _store(self) -> str:
        return f"/catalog/store/{self.site.store_id}/"

    def _is_category(self, url: str) -> bool:
        return self._store() in url and re.search(r"/category/\d+/product\?", url) is not None

    def _is_array(self, url: str) -> bool:
        return self._store() in url and "/productsArray?" in url

    def _learn(self, urls: list[str]) -> None:
        for url in urls:
            match = _STORE_URL.search(url)
            if match and match.group(1) == str(self.site.store_id):
                self.catalog_id = int(match.group(2))
                return

    # --- la interfaz de los conectores

    def list_category(self, slug: str) -> list[ShopProduct]:
        _label, path, _default = self.site.categories[slug]
        session = browser.require(self.key)
        responses = session.open(
            self.key, self.site.base + path,
            want=lambda url: self._is_category(url) or self._is_array(url),
            ready=lambda urls: any(map(self._is_category, urls)) and any(map(self._is_array, urls)),
        )
        self._learn([r.url for r in responses])
        category = next((r for r in responses if self._is_category(r.url) and isinstance(r.data, dict)), None)
        if category is None:
            raise ShopError("la respuesta no era la esperada (sin categoría)")
        ids = category_ids(category.data)[:PER_CATEGORY]
        products: dict[str, dict] = {}
        template = None
        for response in responses:
            if self._is_array(response.url) and isinstance(response.data, dict):
                template = template or response.url
                for product in response.data.get("products") or []:
                    if isinstance(product, dict) and product.get("id") is not None:
                        products.setdefault(str(product["id"]), product)
        left = [i for i in ids if i not in products]
        template = template or array_url(category.url)
        for start in range(0, len(left), BATCH):
            status, data = session.fetch_json(self.key, with_ids(template, left[start : start + BATCH]))
            if status != 200 or not isinstance(data, dict):
                if products:
                    break  # con lo que ya hay basta: no se insiste
                raise ShopError(f"HTTP {status}")
            for product in data.get("products") or []:
                if isinstance(product, dict) and product.get("id") is not None:
                    products.setdefault(str(product["id"]), product)
        order = {product_id: index for index, product_id in enumerate(ids)}
        ranked = sorted(products.items(), key=lambda pair: order.get(pair[0], len(order)))
        return parse_products([product for _id, product in ranked], self.site, slug)

    def detail(self, store_data: dict) -> ShopDetail | None:
        """La ficha de un color. Con la instantánea del listado si es reciente o si no hay navegador
        (una petición HTTP normal: elegir otro color); si no, se pide a la tienda."""
        if not str(store_data.get("id") or "").isdigit():
            return None
        has_snap = isinstance(store_data.get("snap"), dict)
        if has_snap and (fresh(store_data) or not browser.active()):
            return detail_from(self.site, store_data)
        if not browser.active():
            raise NeedsBrowser(f"{self.name} se lee con navegador: la ficha llega con la próxima consulta")
        snap = self._fetch_snapshot(store_data)
        if snap is None:
            return None
        detail = detail_from(self.site, store_data, snap)
        if detail is not None:
            detail.store_data = {**detail.store_data, "snap": snap}  # se guarda la instantánea nueva
        return detail

    def _fetch_snapshot(self, store_data: dict) -> dict | None:
        session = browser.require(self.key)
        if not session.host().startswith(self.site.origin + "/"):
            # Primero, la página del producto: la petición sale luego desde dentro, como en la web.
            url = product_url(self.site, str(store_data.get("page") or self.site.path), str(store_data.get("bundle")),
                              str(store_data.get("color")))
            self._learn([r.url for r in session.open(self.key, url, want=self._is_any, ready=lambda urls: bool(urls), wait=8)])
        url = (f"{self.site.origin}/itxrest/2/catalog/store/{self.site.store_id}/{self.catalog_id}/category/0/product/"
               f"{store_data['id']}/detail?languageId=-2&appId=1")
        status, data = session.fetch_json(self.key, url)
        if status in (400, 404, 410) or (status == 200 and not isinstance(data, dict)):
            return None
        if status != 200:
            raise ShopError(f"HTTP {status}")
        return snapshot(data, self.site)

    def _is_any(self, url: str) -> bool:
        return self._store() in url

    def reference(self, store_data: dict) -> str | None:
        return reference(store_data)

    def search(self, query: str, limit: int = 12) -> list[ShopProduct]:
        """Sin buscador: el navegador no se abre dentro de una petición HTTP. A un enlace de esta tienda
        se le explica por qué; lo demás no es cosa suya."""
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
