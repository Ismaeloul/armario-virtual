"""Conector de Uniqlo (Francia, hombre). Se lee CON NAVEGADOR y solo por el listado (ver listing.py).

Investigado el 18-11-2026: la web da «Access Denied» de Akamai a un programa. Su API de catálogo respondía a
un cliente normal con un identificador de la web en una cabecera, pero eso NO se hace (decisión del proyecto:
no se imitan cabeceras ni identificadores de su web). Se abre la sección con el navegador de serie, como un
usuario, y se ESCUCHAN las respuestas de catálogo que pide la propia página (`/api/commerce/v5/fr/products?
path=<género>,<clase>,<categoría>&offset=…`); para las siguientes, se baja la página hasta el final, como con
la rueda, y se escucha lo que pide.

- Cada producto trae todos sus colores; de cada color, una foto principal. Solo se proponen los colores cuya
  foto es de producto SIN modelo (`images.main[<color>].model` vacío, rutas `WesternCommon/…/goods_…`): cada
  uno es un producto aparte, y los demás colores (solo con modelo) no se ofrecen.
- Sin tallas con stock en el listado: «Tallas: míralas en la tienda». Sin composición (está en la ficha, que
  no se abre).
- El 18-11-2026, la primera página abierta con el navegador ya dio «Access Denied» (status 200): SIN PROBAR de
  verdad. Las direcciones de las secciones (`/fr/fr/men/<clase>/<categoría>`) salen de las claves de su
  taxonomía y no se han podido comprobar.
"""
import math
from urllib.parse import parse_qs, urlsplit

from . import browser, crawl
from .base import ShopError
from .listing import Entry, ListingConnector, euros, fix_text, make_product

BASE = "https://www.uniqlo.com"
PHOTO_WIDTH = 1280
MORE_WAIT = 15.0
MEN = 37609  # el género «hombre» de su taxonomía
_GENDERS = {"MEN", "UNISEX", ""}

# slug -> (nombre para el usuario, ruta de la web, tipo por defecto, id de la categoría en su taxonomía)
SECTIONS = {
    "t-shirts": ("Camisetas", "/fr/fr/men/tops/t-shirts", "camiseta", 85071),
    "sweats": ("Sudaderas", "/fr/fr/men/tops/sweatshirts-and-hoodies", "sudadera", 85072),
    "chemises": ("Camisas", "/fr/fr/men/shirts-and-polos/casual-shirts", "camisa", 100164),
    "chemises-habillees": ("Camisas de vestir", "/fr/fr/men/shirts-and-polos/dress-shirts", "camisa", 100163),
    "polos": ("Polos", "/fr/fr/men/shirts-and-polos/polo-shirts", "polo", 100165),
    "pulls": ("Jerséis", "/fr/fr/men/jumpers/jumpers", "jersey", 100161),
    "cardigans": ("Cárdigans", "/fr/fr/men/jumpers/cardigan", "jersey", 151423),
    "blousons": ("Chaquetas", "/fr/fr/men/outerwear/blousons-and-parkas", "chaqueta", 85067),
    "manteaux": ("Abrigos", "/fr/fr/men/outerwear/coats", "abrigo", 85068),
    "doudounes": ("Plumíferos", "/fr/fr/men/outerwear/down-coats-and-parkas", "abrigo", 85070),
    "jeans": ("Vaqueros", "/fr/fr/men/bottoms/jeans", "vaquero", 85081),
    "chinos": ("Chinos", "/fr/fr/men/bottoms/chinos", "chino", 85080),
    "pantalons": ("Pantalones", "/fr/fr/men/bottoms/casual-trousers", "pantalón", 85082),
    "shorts": ("Bermudas", "/fr/fr/men/bottoms/shorts", "pantalón corto", 85087),
}


def _query(url: str) -> dict:
    return parse_qs(urlsplit(url).query)


def is_listing(url: str, category: int | None = None) -> bool:
    """¿Es la respuesta de catálogo de la página (de esa categoría, si se dice)?"""
    if "/api/commerce/v5/" not in url or "/products?" not in url:
        return False
    path = ",".join(_query(url).get("path", []))
    return bool(path) and (category is None or str(category) in path.split(","))


def offset_of(url: str) -> int:
    try:
        return int(_query(url).get("offset", ["0"])[0])
    except ValueError:
        return 0


def _photo(url: str) -> str:
    return f"{url.split('?')[0]}?width={PHOTO_WIDTH}"


def entries(item: dict) -> list[Entry]:
    """Los colores con foto de producto sin modelo de un producto del listado, cada uno como un producto."""
    product_id, group = str((item or {}).get("productId") or ""), str((item or {}).get("priceGroup") or "00")
    if not product_id or str(item.get("genderCategory") or "").upper() not in _GENDERS:
        return []
    prices = item.get("prices") or {}
    price = euros(((prices.get("promo") or {}).get("value")) or (prices.get("base") or {}).get("value"))
    main = (item.get("images") or {}).get("main") or {}
    subs = [s for s in (item.get("images") or {}).get("sub") or [] if isinstance(s, dict)]
    flat = []
    for color in item.get("colors") or []:
        code = str((color or {}).get("displayCode") or "")
        image = main.get(code) or {}
        if code and image.get("image") and not image.get("model"):
            flat.append(color)
    ref = str(item.get("l1Id") or "")
    found = []

    def link(code: str) -> str:
        return f"{BASE}/fr/fr/products/{product_id}/{group}?colorDisplayCode={code}"

    colors = [{"id": f"{product_id}-{group}-{c['displayCode']}", "name": fix_text(c.get("name")).capitalize(),
               "url": link(c["displayCode"])} for c in flat]
    for color in flat:
        code = color["displayCode"]
        photos = [_photo(main[code]["image"])]
        for sub in subs:  # otras vistas sin modelo del mismo color (las que no dicen color son de otro)
            if str(sub.get("colorCode") or "") == code and not sub.get("model") and sub.get("image"):
                photos.append(_photo(sub["image"]))
        found.append(Entry(
            id=f"{product_id}-{group}-{code}",
            name=fix_text(item.get("name")),
            price_cents=price,
            # Rebajado: `prices.promo` (el de ahora) por debajo de `prices.base` (el de siempre). Visto en los
            # listados guardados (39,90 € con 49,90 € antes).
            old_price_cents=euros((prices.get("base") or {}).get("value")) if prices.get("promo") else None,
            old_price_known=True,
            url=link(code),
            color=fix_text(color.get("name")).capitalize(),
            photos=photos,
            sizes=None,  # el listado no dice qué tallas quedan
            colors=colors,
            ref=ref,
            # La familia de color normalizada, en inglés («BLACK»), por si el nombre no dice nada conocido.
            color_hint=str(color.get("filterCode") or ""),
        ))
    return found


def parse_listing(data: dict, section: str) -> tuple[list, int, int | None]:
    """(productos, productos de la respuesta, total de la sección) de una respuesta de catálogo."""
    result = (data or {}).get("result") if isinstance((data or {}).get("result"), dict) else data or {}
    items = result.get("items") or []
    default = SECTIONS[section][2] if section in SECTIONS else None
    products, refs = [], set()
    for item in items:
        for found in entries(item):
            product = make_product("uniqlo", "Uniqlo", found, section, default)
            if product is None or product.product_ref in refs:
                continue
            refs.add(product.product_ref)
            products.append(product)
    total = (result.get("pagination") or {}).get("total")
    return products, len(items), total if isinstance(total, int) else None


class UniqloConnector(ListingConnector):
    key = "uniqlo"
    name = "Uniqlo"
    domain = "uniqlo.com"
    # No se sabe qué día saca novedades: los lunes (ver el reparto en shops/__init__.py).
    refresh_weekday = 0  # lunes = 0
    categories = {slug: label for slug, (label, _path, _type, _id) in SECTIONS.items()}
    section_types = {slug: kind for slug, (_label, _path, kind, _id) in SECTIONS.items()}

    def list_category(self, slug: str) -> list:
        """La sección: la página y su catálogo; después, bajar hasta el final para que pida los siguientes,
        hasta el total o el tope. Si falla a mitad, `crawl.Partial` con lo leído."""
        _label, path, _type, category = SECTIONS[slug]
        session = browser.require(self.key)
        found: dict[str, object] = {}
        offsets: set[int] = set()
        limit = max(1, crawl.max_pages(self.key))

        def want(url: str) -> bool:
            return is_listing(url, category)

        def take(responses) -> tuple[int | None, int]:
            total, size = None, 0
            for response in sorted(responses, key=lambda r: offset_of(r.url)):
                offset = offset_of(response.url)
                if offset in offsets or not isinstance(response.data, dict):
                    continue
                offsets.add(offset)
                products, raw, total_here = parse_listing(response.data, slug)
                total, size = total_here if total_here is not None else total, max(size, raw)
                for product in products:
                    found.setdefault(product.product_ref, product)
            return total, size

        crawl.before_page()
        responses = session.open(self.key, BASE + path, want=want, ready=lambda urls: any(map(want, urls)))
        total, size = take(responses)
        if not offsets:
            raise ShopError("la respuesta no era la esperada (sin catálogo)")
        crawl.page_read(len(found))
        if total and size:
            crawl.section_total(min(limit, math.ceil(total / size)))
        try:
            for _page in range(1, limit):
                if total is not None and size and len(offsets) * size >= total:
                    break
                crawl.before_page()
                before, count = len(offsets), len(found)
                more = session.more(self.key, want=want, wait=MORE_WAIT,
                                    ready=lambda urls: any(offset_of(u) not in offsets for u in urls))
                total_here, _size = take(more)
                total = total_here if total_here is not None else total
                crawl.page_read(len(found) - count)
                if len(offsets) == before:
                    break  # bajando ya no pide más: no hay más
        except ShopError as exc:
            if not found:
                raise
            raise crawl.Partial(list(found.values()), exc) from exc
        return list(found.values())
