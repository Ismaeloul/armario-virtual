"""Conector de H&M (Francia, hombre). Se lee CON NAVEGADOR y solo por el listado (ver listing.py).

Investigado el 18-11-2026: sin navegador, «Access Denied» de Akamai; con el navegador de serie, las páginas de
sección cargan y traen sus datos en el `__NEXT_DATA__` (`plpProps.productListingSectionProps.productListingData`):
36 artículos por página (`?page=N`), cada artículo es un producto en un color. La FICHA da «Access Denied»
también con navegador: NO se abre nunca.

- Cada artículo trae nombre, precio, color con su tono, sus otros colores (`swatches`) y la foto de producto
  sin modelo (`productImage`, de tipo `DescriptiveStillLife`). Sin composición ni descripción.
- Tallas: el listado trae unas `sizes` con un `stock` en cifras que no está claro qué dice (0, 1, 2…); de
  momento H&M sale SIN tallas («Tallas: míralas en la tienda»), y al comprar se elige «Sin talla» o se escribe.
- Son ~5.100 artículos de hombre (~145 páginas): demasiado para leerlo entero cada semana. Por defecto solo las
  primeras 8 páginas de cada sección (`config.SHOP_STORE_PAGES`, se cambia con ARMARIO_SHOP_MAX_PAGES_HM), y
  ordenadas por novedad con el propio parámetro de la web (`SORT`).
- Se quitan los lotes («Lot de 3 T-shirts», `isMultipack`) y la ropa de casa (pijamas, «ensemble d'intérieur»).
"""
from .base import ShopError
from .listing import Entry, ListingConnector, euros, fix_text, hex_color, make_product, page_by_page

BASE = "https://www2.hm.com"
PHOTO_WIDTH = 1280
# El orden «Plus récent» de la web, como lo pone ella en la dirección. Sin probar a fondo (ver el informe).
SORT = "newProduct"
STILL_LIFE = "DescriptiveStillLife"

# slug -> (nombre para el usuario, ruta, tipo por defecto)
SECTIONS = {
    "t-shirts": ("Camisetas", "/fr_fr/homme/catalogue-par-produit/t-shirts-et-debardeurs.html", "camiseta"),
    "polos": ("Polos", "/fr_fr/homme/catalogue-par-produit/polos.html", "polo"),
    "chemises": ("Camisas", "/fr_fr/homme/catalogue-par-produit/chemises.html", "camisa"),
    "sweats": ("Sudaderas", "/fr_fr/homme/catalogue-par-produit/sweats.html", "sudadera"),
    "pulls": ("Punto", "/fr_fr/homme/catalogue-par-produit/pulls-cardigans.html", "jersey"),
    "vestes": ("Chaquetas y abrigos", "/fr_fr/homme/catalogue-par-produit/vestes-et-manteaux.html", "chaqueta"),
    "pantalons": ("Pantalones", "/fr_fr/homme/catalogue-par-produit/pantalons.html", "pantalón"),
    "jeans": ("Vaqueros", "/fr_fr/homme/catalogue-par-produit/jeans.html", "vaquero"),
    "shorts": ("Bermudas", "/fr_fr/homme/catalogue-par-produit/shorts.html", "pantalón corto"),
    "baskets": ("Zapatillas", "/fr_fr/homme/chaussures/baskets.html", "zapatillas"),
}


def listing_data(data: dict) -> dict:
    """`productListingData` del `__NEXT_DATA__` de una página de sección (o el propio, si ya lo es)."""
    if "rawProductList" in data:
        return data
    props = ((data.get("props") or {}).get("pageProps") or {}).get("plpProps") or {}
    found = (props.get("productListingSectionProps") or {}).get("productListingData")
    if not isinstance(found, dict):
        raise ShopError("la respuesta no era la esperada (sin listado)")
    return found


def _photo(url: str) -> str:
    return f"{url.split('?')[0]}?imwidth={PHOTO_WIDTH}"


def entry(raw: dict) -> Entry | None:
    """Un artículo del listado. None si no sirve (un lote, sin id)."""
    if not isinstance(raw, dict) or not str(raw.get("id") or "").isdigit() or raw.get("isMultipack"):
        return None
    photos: list[str] = []
    info = raw.get("productImageInfo") or {}
    if raw.get("productImage") and str(info.get("assetType") or STILL_LIFE) == STILL_LIFE:
        photos.append(str(raw["productImage"]))
    for image in raw.get("images") or []:
        url = str((image or {}).get("url") or "")
        if url and (image or {}).get("assetType") == STILL_LIFE and url not in photos:
            photos.append(url)
    prices = [euros((p or {}).get("price")) for p in raw.get("prices") or []]
    prices = [p for p in prices if p]
    colors = []
    for swatch in raw.get("swatches") or []:
        article = str((swatch or {}).get("articleId") or "")
        if article.isdigit():
            colors.append({"id": article, "name": swatch.get("colorName"), "hex": hex_color(swatch.get("colorCode")),
                           "url": BASE + str(swatch.get("url") or f"/fr_fr/productpage.{article}.html")})
    return Entry(
        id=str(raw["id"]),
        name=fix_text(raw.get("productName")),
        price_cents=min(prices) if prices else None,
        url=BASE + str(raw.get("url") or f"/fr_fr/productpage.{raw['id']}.html"),
        color=fix_text(raw.get("colorName")),
        hex=hex_color(raw.get("colors")),
        photos=[_photo(p) for p in photos],
        sizes=None,  # ver arriba: sin tallas
        colors=colors,
        brand=fix_text(raw.get("brandName")),
        ref=str(raw["id"]),
        hint=str(raw.get("mainCatCode") or ""),
    )


def parse_listing(data: dict, section: str) -> tuple[list, int, int | None]:
    """(productos, artículos de la página, páginas de la sección) de un `__NEXT_DATA__`."""
    listing = listing_data(data)
    raws = listing.get("rawProductList") or []
    default = SECTIONS[section][2] if section in SECTIONS else None
    products, refs = [], set()
    for raw in raws:
        found = entry(raw)
        product = make_product("hm", "H&M", found, section, default) if found else None
        if product and product.product_ref not in refs:
            refs.add(product.product_ref)
            products.append(product)
    pages = (listing.get("pagination") or {}).get("totalPages")
    return products, len(raws), pages if isinstance(pages, int) else None


def page_url(path: str, number: int) -> str:
    query = [f"sort={SORT}"] if SORT else []
    if number > 1:
        query.append(f"page={number}")
    return BASE + path + (f"?{'&'.join(query)}" if query else "")


class HMConnector(ListingConnector):
    key = "hm"
    name = "H&M"
    domain = "hm.com"
    # No se sabe qué día saca novedades: los jueves (ver el reparto en shops/__init__.py).
    refresh_weekday = 3  # lunes = 0
    categories = {slug: label for slug, (label, _path, _type) in SECTIONS.items()}
    section_types = {slug: kind for slug, (_label, _path, kind) in SECTIONS.items()}

    def list_category(self, slug: str) -> list:
        """Las primeras páginas de la sección (las más nuevas), hasta el tope de H&M (8 por defecto)."""
        _label, path, _type = SECTIONS[slug]
        return page_by_page(self.key, lambda n: page_url(path, n), lambda data: parse_listing(data, slug))

