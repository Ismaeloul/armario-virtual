"""Conector de Weekday (Francia, hombre; grupo H&M). Se lee CON NAVEGADOR y solo por el listado (ver listing.py).

Investigado el 18-11-2026: sin navegador, «Access Denied» de Akamai; con el navegador de serie, las secciones
cargan y traen sus datos en el `__NEXT_DATA__` (`props.pageProps.blocks[]`, el bloque `product-listing` →
`listingPageData`): 40 productos por página (`?page=N`), cada uno en un color. La FICHA da «Access Denied»
también con navegador: NO se abre nunca.

El listado ya trae casi todo: tallas con stock (`sizeVariants[].inStock`), los otros colores con su tono
(`colorVariants`) y la foto de producto sin modelo (`StillMedia/DescriptiveStillLife`). Sin composición.
El catálogo de hombre son ~660 productos (17 páginas): se lee entero.
"""
import re

from .base import ShopError
from .listing import Entry, ListingConnector, euros, fix_text, hex_color, make_product, page_by_page

BASE = "https://www.weekday.com"
STILL_LIFE = "StillMedia/DescriptiveStillLife"
_SKU = re.compile(r"(\d{7,13})/?$")

# slug -> (nombre para el usuario, ruta, tipo por defecto)
SECTIONS = {
    "t-shirts": ("Camisetas y polos", "/fr-fr/men/t-shirts-and-tops/", "camiseta"),
    "shirts": ("Camisas", "/fr-fr/men/shirts/", "camisa"),
    "hoodies": ("Sudaderas con capucha", "/fr-fr/men/hoodies/", "sudadera"),
    "sweatshirts": ("Sudaderas", "/fr-fr/men/sweatshirts/", "sudadera"),
    "knitwear": ("Punto", "/fr-fr/men/knitwear/", "jersey"),
    "jackets": ("Chaquetas y abrigos", "/fr-fr/men/jackets-and-coats/", "chaqueta"),
    "trousers": ("Pantalones", "/fr-fr/men/trousers/", "pantalón"),
    "jeans": ("Vaqueros", "/fr-fr/men/jeans/", "vaquero"),
    "shorts": ("Bermudas", "/fr-fr/men/shorts/", "pantalón corto"),
}


def listing_data(data: dict) -> dict:
    """`listingPageData` del bloque `product-listing` del `__NEXT_DATA__` (o el propio, si ya lo es)."""
    if "products" in data and "pagination" in data:
        return data
    blocks = ((data.get("props") or {}).get("pageProps") or {}).get("blocks") or []
    for block in blocks:
        if isinstance(block, dict) and block.get("component") == "product-listing":
            found = block.get("listingPageData")
            if isinstance(found, dict):
                return found
    raise ShopError("la respuesta no era la esperada (sin listado)")


def entry(raw: dict) -> Entry | None:
    sku = str((raw or {}).get("sku") or "")
    if not sku.isdigit():
        return None
    media = raw.get("media") or {}
    images = [i for i in media.get("images") or [] if isinstance(i, dict) and i.get("assetType") == STILL_LIFE]
    images.sort(key=lambda i: not i.get("isHero"))
    photos = []
    for image in images:
        url = str(image.get("url") or "")
        if url and url not in photos:
            photos.append(url)
    sizes = []
    for size in raw.get("sizeVariants") or []:
        label = str((size or {}).get("label") or "").strip()
        if label and label not in (s[0] for s in sizes):
            sizes.append([label, str(size.get("inStock") or "").lower() in ("yes", "true", "1")])
    colors = []
    for variant in raw.get("colorVariants") or []:
        match = _SKU.search(str((variant or {}).get("uri") or (variant or {}).get("url") or ""))
        if match:
            colors.append({"id": match.group(1), "name": variant.get("label"), "hex": hex_color(variant.get("color")),
                           "url": BASE + str(variant.get("url") or "")})
    if colors and not any(c["id"] == sku for c in colors):
        colors.append({"id": sku, "name": raw.get("variantName"), "hex": hex_color((media.get("swatch") or {}).get("hex")),
                       "url": BASE + str(raw.get("url") or "")})
    pricing = raw.get("pricing") or {}
    return Entry(
        id=sku,
        name=fix_text(raw.get("name")),
        price_cents=euros(pricing.get("priceAsNumber")),
        # Rebajado: `priceBeforeDiscountAsNumber` (el de antes de la rebaja, igual a `originalPrice`) mayor que
        # `priceAsNumber`, con `isOnSale`. Visto en un listado guardado (45 € con 89,99 € antes).
        old_price_cents=euros(pricing.get("priceBeforeDiscountAsNumber")),
        old_price_known=True,
        url=BASE + str(raw.get("url") or ""),
        color=fix_text(raw.get("variantName")),
        hex=hex_color((media.get("swatch") or {}).get("hex")),
        photos=photos,
        sizes=sizes or None,
        colors=colors,
        brand=fix_text(raw.get("brandName")),
        ref=sku,
        hint=str(raw.get("categoryUri") or ""),
        sold_out=bool(sizes) and not any(stock for _name, stock in sizes),
    )


def parse_listing(data: dict, section: str) -> tuple[list, int, int | None]:
    """(productos, productos de la página, páginas de la sección) de un `__NEXT_DATA__`."""
    listing = listing_data(data)
    raws = listing.get("products") or []
    default = SECTIONS[section][2] if section in SECTIONS else None
    products, refs = [], set()
    for raw in raws:
        found = entry(raw)
        product = make_product("weekday", "Weekday", found, section, default) if found else None
        if product and product.product_ref not in refs:
            refs.add(product.product_ref)
            products.append(product)
    pagination = listing.get("pagination") or {}
    try:
        pages = -(-int(pagination["totalProducts"]) // max(1, int(pagination.get("limit") or 40)))
    except (KeyError, TypeError, ValueError):
        pages = None
    return products, len(raws), pages


def page_url(path: str, number: int) -> str:
    return BASE + path + (f"?page={number}" if number > 1 else "")


class WeekdayConnector(ListingConnector):
    key = "weekday"
    name = "Weekday"
    domain = "weekday.com"
    # No se sabe qué día saca novedades: los domingos (ver el reparto en shops/__init__.py).
    refresh_weekday = 6  # lunes = 0
    categories = {slug: label for slug, (label, _path, _type) in SECTIONS.items()}
    section_types = {slug: kind for slug, (_label, _path, kind) in SECTIONS.items()}

    def list_category(self, slug: str) -> list:
        """La sección entera, página a página (`?page=N`), hasta la última."""
        _label, path, _type = SECTIONS[slug]
        return page_by_page(self.key, lambda n: page_url(path, n), lambda data: parse_listing(data, slug))
