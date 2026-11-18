"""Conector de Jules (jules.com/fr-fr): toda la tienda es de hombre. Se lee con navegador: ver sfra.py.

Investigado el 18-11-2026 (Chromium de serie con ventana, sin captcha; a httpx, Cloudflare le da 403). Las
fotos sí responden a un cliente normal.

- Rejilla: `Search-UpdateGrid?cgid=…&start=…&sz=32`. Cada producto: `data-pid` (modelo + color:
  «7275939010» = modelo 727593 + color 9010), el nombre en `a.pdp-title-link`, el precio en
  `data-unitpriceati` (el de ahora, con la rebaja). El color no viene en la rejilla (solo circulitos sin
  nombre): sale en la ficha.
- Ficha (`Product-Variation`): `colorDisplayValue` («Blanc», «Écru»), `composition`, tallas y los colores
  del modelo (`selectable` = existen ahora; el pid de otro color es `masterID` + su id).
- Fotos: `_V11` es la de delante sin modelo (fondo gris muy claro); las demás llevan modelo o son
  detalles. No hay foto de detrás sin modelo.
- Secciones: las que corresponden a las nuestras; Novedades va dentro de todas (`covered_by`).
"""
import html
import re

from .base import ShopDetail, ShopProduct
from .sfra import SfraConnector, SfraSite, cents, color_values, list_price, make_product, sizes_of, text_of, tiles

ORIGIN = "https://www.jules.com"
PHOTO = "sw=1300&sh=1500&sm=fit"
SITE = SfraSite(
    key="jules",
    name="Jules",
    origin=ORIGIN,
    site_id="Sites-Jules-SFRA-Site",
    home="/fr-fr/l/nouveautes/",
    categories={
        "t-shirt": ("Camisetas", "/fr-fr/l/t-shirt/", "HCC25", "camiseta"),
        "polo": ("Polos", "/fr-fr/l/polo/", "HCC19", "polo"),
        "chemises": ("Camisas", "/fr-fr/l/chemises/", "GROUPE-CHEMISE", "camisa"),
        "surchemise": ("Sobrecamisas", "/fr-fr/l/surchemise/", "Surchemise", "sobrecamisa"),
        "sweat": ("Sudaderas", "/fr-fr/l/sweat/", "HCC23", "sudadera"),
        "pull": ("Punto", "/fr-fr/l/pull/", "HCC20", "jersey"),
        "manteau-blouson": ("Chaquetas y abrigos", "/fr-fr/l/manteau-blouson/", "GROUPE-BLOUSONS-CUIRS", "chaqueta"),
        "pantalon": ("Pantalones", "/fr-fr/l/pantalon/", "GROUPE-PANTALONS", "pantalón"),
        "jeans": ("Vaqueros", "/fr-fr/l/jeans/", "HCC15", "vaquero"),
        "short-bermuda": ("Bermudas", "/fr-fr/l/short-bermuda/", "HCC01", "pantalón corto"),
        "chaussures": ("Calzado", "/fr-fr/l/chaussures/", "HCA07", "zapatillas"),
        # Lo nuevo de todo (también accesorios): sin tipo por defecto, solo lo que el nombre dice.
        "nouveautes": ("Novedades", "/fr-fr/l/nouveautes/", "NOUVEAUTES", None),
    },
    covered_by={"nouveautes": ("t-shirt", "polo", "chemises", "surchemise", "sweat", "pull", "manteau-blouson",
                               "pantalon", "jeans", "short-bermuda", "chaussures")},
    page_size=32,
    paging="start",
)

_NAME = re.compile(r'class="link pdp-title-link"[^>]*>\s*(.*?)\s*</a>', re.S)
_PRICE = re.compile(r'data-unitpriceati="([\d.,]+)"')
_FRONT = re.compile(r"_V11\.(?:jpg|png)", re.IGNORECASE)


def product_url(pid: str) -> str:
    return f"{ORIGIN}/fr-fr/p/{pid}.html"


def parse_grid(page: str, section: str) -> list[ShopProduct]:
    """De la rejilla de `Search-UpdateGrid` a productos (sin color: llega con la ficha)."""
    default = SITE.categories.get(section, (None, None, None, None))[3]
    found: list[ShopProduct] = []
    for pid, chunk in tiles(page):
        name = _NAME.search(chunk)
        price = _PRICE.search(chunk)
        product = make_product(
            SITE, pid=pid, name=html.unescape(name.group(1)) if name else "", price=cents(price.group(1)) if price else None,
            url=product_url(pid), section=section, default_type=default,
        )
        if product is not None:
            found.append(product)
    return found


def _photo(url: str) -> str:
    return f"{url.split('?')[0]}?{PHOTO}"


def parse_variation(product: dict, store_data: dict | None = None) -> ShopDetail:
    """De `Product-Variation` (su `product`) a la ficha de ese color."""
    pid = str(product.get("id") or "")
    master = str(product.get("masterID") or "")
    images = [str((i or {}).get("url") or "") for i in (product.get("images") or {}).get("large") or []]
    images = [i for i in images if i.startswith("https://")]
    front = next((i for i in images if _FRONT.search(i.split("?")[0])), None)
    photos, model = ([_photo(front)], False) if front else (([_photo(images[0])], True) if images else ([], False))
    siblings = []
    own = str(product.get("colorID") or "")
    for value in color_values(product):
        color_id = str(value.get("id") or "")
        if not color_id.isdigit() or not master or (not value.get("selectable") and color_id != own):
            continue
        other = master + color_id
        if any(s["product_ref"] == f"jules:{other}" for s in siblings):
            continue
        siblings.append({
            "product_ref": f"jules:{other}", "name": " ".join(str(value.get("displayValue") or "").split()),
            "hex": None, "url": product_url(other), "store_data": {"pid": other, "url": product_url(other)},
        })
    colour = " ".join(str(product.get("colorDisplayValue") or "").split())
    if siblings and pid and not any(s["product_ref"] == f"jules:{pid}" for s in siblings):
        siblings.append({"product_ref": f"jules:{pid}", "name": colour, "hex": None, "url": product_url(pid),
                         "store_data": {"pid": pid, "url": product_url(pid)}})
    sales = ((product.get("price") or {}).get("sales") or {}).get("value")
    composition = " ".join(str(product.get("composition") or "").split()).rstrip(".")
    return ShopDetail(
        price_cents=cents(sales),
        old_price_cents=list_price(product),
        old_price_known=True,
        sizes=sizes_of(product),
        photo_urls=photos,
        description=text_of(str(product.get("longDescription") or ""))[:400],
        composition=composition[:300],
        siblings=sorted(siblings, key=lambda s: s["product_ref"]) if len(siblings) > 1 else [],
        store_color=colour,
        store_data={"model_photo": True} if model else {},
    )


class JulesConnector(SfraConnector):
    def __init__(self):
        # No se sabe qué día saca novedades: los miércoles (reparto de noches, ver shops/__init__.py).
        super().__init__(SITE, refresh_weekday=2)

    def parse_grid(self, page: str, section: str) -> list[ShopProduct]:
        return parse_grid(page, section)

    def parse_variation(self, data: dict, store_data: dict) -> ShopDetail | None:
        return parse_variation(data, store_data)
