"""Conector de COS (Francia, hombre; grupo H&M). Se lee CON NAVEGADOR y solo por el listado (ver listing.py).

Investigado el 18-11-2026: sin navegador, «Access Denied» de Akamai (la web y su API). Con el navegador de
serie, la página de cada sección pide ella sola su listado a `api.cos.com/product-search/…` (32 productos, con
`offset`), y el botón «Charger la page suivante» de la propia web pide los siguientes. Se abre la sección, se
ESCUCHA esa respuesta y se pulsa el botón como lo haría un usuario, una vez por página. No se llama a esa API
por nuestra cuenta (ni con la cabecera `touchpoint` que pone la web). La FICHA da «Access Denied» también con
navegador: NO se abre nunca.

El listado trae nombre, precio, el color con su tono, los otros colores (`articleSwatches`) y la foto de
producto sin modelo (`StillMedia/DescriptiveStillLife`). No trae tallas: «Tallas: míralas en la tienda», y al
comprar se elige «Sin talla» o se escribe. Trae también una `composition`, pero NO es la composición: son solo
los materiales certificados que destaca la web (visto el 18-11-2026: «30% laine RWS, 30% alpaga RAS» en una
docena de camisas distintas, «Doublure: 100% lyocell» en una camisa sin forro), así que no se enseña. Cada producto (un color) es un artículo de Centra:
su id va en `product_ref` (es el que dan los otros colores) y su SKU es la referencia.
"""
import math
from urllib.parse import parse_qs, urlsplit

from . import browser, crawl
from .base import ShopError
from .estimate import norm
from .listing import Entry, ListingConnector, euros, fix_text, hex_color, make_product

BASE = "https://www.cos.com"
STILL_LIFE = "StillMedia/DescriptiveStillLife"
NEXT_BUTTON = "button[aria-label='Charger la page suivante']"
MORE_WAIT = 20.0
_MEN = {"homme", "hommes", "unisexe", "unisex", "mixte", "men", "male"}

# slug -> (nombre para el usuario, ruta, tipo por defecto). Sobrecamisas y bermudas no tienen página propia:
# van dentro de Camisas y de Pantalones.
SECTIONS = {
    "t-shirts": ("Camisetas", "/fr-fr/men/t-shirts", "camiseta"),
    "polos": ("Polos", "/fr-fr/men/polo-shirts", "polo"),
    "shirts": ("Camisas", "/fr-fr/men/shirts", "camisa"),
    "sweatshirts": ("Sudaderas", "/fr-fr/men/sweatshirts", "sudadera"),
    "knitwear": ("Punto", "/fr-fr/men/knitwear", "jersey"),
    "coats": ("Chaquetas y abrigos", "/fr-fr/men/coats-and-jackets", "chaqueta"),
    "trousers": ("Pantalones", "/fr-fr/men/trousers", "pantalón"),
    "jeans": ("Vaqueros", "/fr-fr/men/jeans", "vaquero"),
    "shoes": ("Zapatos", "/fr-fr/men/shoes", "zapatos"),
}


def is_listing(url: str) -> bool:
    return "api.cos.com/product-search/" in url and "offset=" in url


def offset_of(url: str) -> int | None:
    try:
        return int(parse_qs(urlsplit(url).query).get("offset", [""])[0])
    except ValueError:
        return None


def entry(raw: dict) -> Entry | None:
    attributes = (raw or {}).get("attributes") or {}
    centra = str(raw.get("id") or attributes.get("centraProductId") or "")
    if not centra.isdigit():
        return None
    gender = norm(raw.get("gender"))
    if gender and gender not in _MEN:
        return None
    photos = []
    for media in raw.get("media") or []:
        kind = ((media or {}).get("attributes") or {}).get("imageType")
        url = str((((media or {}).get("source") or {}).get("standard") or {}).get("url") or "")
        if kind == STILL_LIFE and url and url not in photos:
            photos.append(url)
    swatches = [s for s in attributes.get("articleSwatches") or [] if isinstance(s, dict)]
    variant = raw.get("variant") or {}
    own = next((s for s in swatches if str(s.get("displayItemId")) == centra), None)
    url = f"{BASE}/fr-fr/{(raw.get('mainCategory') or {}).get('uri') or 'men'}/product/{raw.get('uri') or ''}"
    colors = [
        {"id": str(s["displayItemId"]), "name": s.get("name"), "hex": hex_color(s.get("hex")),
         "url": url if str(s["displayItemId"]) == centra else ""}
        for s in swatches if str(s.get("displayItemId") or "").isdigit()
    ]
    price = (raw.get("price") or {}).get("value")
    return Entry(
        id=centra,
        name=fix_text(raw.get("name")),
        price_cents=euros(price),
        # `priceBeforeDiscount` (el de antes de la rebaja) junto a `price`: iguales sin rebaja. Es la misma
        # plataforma que Weekday, donde sí se vio uno rebajado; en COS, ninguno en los datos guardados.
        old_price_cents=euros((raw.get("priceBeforeDiscount") or {}).get("value")),
        old_price_known=True,
        url=url,
        # El nombre del color en francés es el de su muestra; el de `variant`, en inglés.
        color=fix_text((own or {}).get("name") or variant.get("name")),
        hex=hex_color(variant.get("hex") or (own or {}).get("hex")),
        photos=photos,
        sizes=None,  # el listado no trae tallas
        # `composition` no es la composición entera (ver arriba): no se guarda.
        colors=colors,
        ref=str(raw.get("sku") or "") or centra,
        hint=f"{(raw.get('details') or {}).get('productType') or ''} {(raw.get('mainCategory') or {}).get('uri') or ''}",
        sold_out=raw.get("hasStock") is False,
    )


def parse_listing(data: dict, section: str) -> tuple[list, int, int | None]:
    """(productos, productos de la respuesta, total de productos de la sección) de una respuesta de la API."""
    body = (data or {}).get("data") if isinstance((data or {}).get("data"), dict) else data or {}
    raws = body.get("products") or []
    default = SECTIONS[section][2] if section in SECTIONS else None
    products, refs = [], set()
    for raw in raws:
        found = entry(raw)
        product = make_product("cos", "COS", found, section, default) if found else None
        if product and product.product_ref not in refs:
            refs.add(product.product_ref)
            products.append(product)
    total = (body.get("pagination") or {}).get("totalProducts")
    return products, len(raws), total if isinstance(total, int) else None


class COSConnector(ListingConnector):
    key = "cos"
    name = "COS"
    domain = "cos.com"
    # No se sabe qué día saca novedades: los sábados (ver el reparto en shops/__init__.py).
    refresh_weekday = 5  # lunes = 0
    categories = {slug: label for slug, (label, _path, _type) in SECTIONS.items()}
    section_types = {slug: kind for slug, (_label, _path, kind) in SECTIONS.items()}

    def list_category(self, slug: str) -> list:
        """La sección: la página y su listado; después, «Charger la page suivante» hasta el final o el tope.
        Si una página siguiente falla o la tienda bloquea a mitad, `crawl.Partial` con lo leído."""
        _label, path, _type = SECTIONS[slug]
        session = browser.require(self.key)
        found: dict[str, object] = {}
        offsets: set[int] = set()
        limit = max(1, crawl.max_pages(self.key))

        def take(responses) -> tuple[int, int | None, int]:
            """Lo nuevo de unas respuestas: (productos nuevos, total de la sección, tamaño de página)."""
            new, total, size = 0, None, 0
            for response in sorted(responses, key=lambda r: offset_of(r.url) or 0):
                offset = offset_of(response.url)
                if offset is None or offset in offsets or not isinstance(response.data, dict):
                    continue
                offsets.add(offset)
                products, raw, total_here = parse_listing(response.data, slug)
                total, size = total_here if total_here is not None else total, max(size, raw)
                for product in products:
                    if product.product_ref not in found:
                        found[product.product_ref] = product
                        new += 1
            return new, total, size

        crawl.before_page()
        responses = session.open(self.key, BASE + path, want=is_listing, ready=lambda urls: any(map(is_listing, urls)))
        new, total, size = take(responses)
        if not offsets:
            raise ShopError("la respuesta no era la esperada (sin listado)")
        crawl.page_read(new)
        if total and size:
            crawl.section_total(min(limit, math.ceil(total / size)))
        try:
            for _page in range(1, limit):
                if total is not None and len(offsets) * max(size, 1) >= total:
                    break
                if len(found) >= crawl.max_products(self.key):
                    break
                crawl.before_page()
                wanted = max(offsets) + max(size, 1)
                before = len(offsets)
                more = session.more(self.key, want=is_listing, click=NEXT_BUTTON, wait=MORE_WAIT,
                                    ready=lambda urls: any(offset_of(u) == wanted for u in urls))
                new, total_here, _size = take(more)
                crawl.page_read(new)
                total = total_here if total_here is not None else total
                if len(offsets) == before:
                    break  # sin botón o sin respuesta nueva: ya no hay más
        except ShopError as exc:
            if not found:
                raise
            raise crawl.Partial(list(found.values()), exc) from exc
        return list(found.values())
