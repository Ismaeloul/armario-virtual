"""Conector de Bonobo (bonoboplanet.com, sección de hombre). Se lee con navegador: ver sfra.py.

Investigado el 18-11-2026 (Chromium de serie con ventana, sin captcha). Cloudflare rechaza a un cliente
normal en todo, también en las FOTOS: se bajan abriéndolas en la propia sesión del navegador
(`Session.image`), como haría cualquiera al abrir la imagen.

- Rejilla: `Search-UpdateGrid?cgid=…&page=N`, 54 por página. Cada producto: su pid (17 cifras, uno por
  color), el nombre con el color dentro («Polo droit manches longues en coton vert kaki homme»), el precio
  y los circulitos de sus colores, que traen el pid y el nombre de cada uno (en el nombre de su foto y en
  su título). El nombre del modelo (sin color) sale de la dirección de esos circulitos.
- Ficha (`Product-Variation`): precio, tallas (`selectable` = quedan), color, composición y fotos.
- Fotos: `vue3` es la de delante sin modelo (fondo gris claro); las demás llevan modelo o son detalles.
- Referencia: el pid, el que sale en el enlace y en «Référence».
"""
import html
import json
import re

from . import browser
from .base import ShopDetail, ShopProduct
from .estimate import norm, sentence_case
from .sfra import SfraConnector, SfraSite, cents, color_values, list_price, make_product, sizes_of, text_of, tiles

ORIGIN = "https://www.bonoboplanet.com"
IMAGES = f"{ORIGIN}/dw/image/v2/BCHM_PRD"
PHOTO = "sw=1300&sh=1690"
SITE = SfraSite(
    key="bonobo",
    name="Bonobo",
    origin=ORIGIN,
    site_id="Sites-BNB_FR_SFRA-Site",
    home="/nouveautes-homme-s",
    categories={
        "t-shirts": ("Camisetas", "/t-shirts-homme-sch_010900", "SCH_010900", "camiseta"),
        "polos": ("Polos", "/polos-homme-sch_011700", "SCH_011700", "polo"),
        "chemises": ("Camisas", "/chemises-homme-sch_010100", "SCH_010100", "camisa"),
        "surchemises": ("Sobrecamisas", "/surchemises-homme-tph_010108", "TPH_010108", "sobrecamisa"),
        "sweats": ("Sudaderas", "/sweats-homme-sch_011200", "SCH_011200", "sudadera"),
        "pulls": ("Punto", "/pulls-homme-sch_010700", "SCH_010700", "jersey"),
        "vestes": ("Chaquetas", "/vestes-homme-sch_011000", "SCH_011000", "chaqueta"),
        "manteaux": ("Abrigos", "/manteaux-homme-sch_010500", "SCH_010500", "abrigo"),
        "pantalons": ("Pantalones", "/pantalons-homme-sch_010600", "SCH_010600", "pantalón"),
        "jeans": ("Vaqueros", "/jeans-homme-sch_010300", "SCH_010300", "vaquero"),
        "bermudas": ("Bermudas", "/bermudas-shorts-homme-sch_011100", "SCH_011100", "pantalón corto"),
        "baskets": ("Zapatillas", "/baskets-homme-tph_020302", "TPH_020302", "zapatillas"),
        # Lo nuevo de todo (también accesorios): sin tipo por defecto, solo lo que el nombre dice.
        "nouveautes": ("Novedades", "/nouveautes-homme-s", "nouveautes-h", None),
    },
    covered_by={"nouveautes": ("t-shirts", "polos", "chemises", "surchemises", "sweats", "pulls", "vestes",
                               "manteaux", "pantalons", "jeans", "bermudas", "baskets")},
    page_size=54,
    paging="page",
)

_TAGCO = re.compile(r'data-tagco="([^"]+)"')
_NAME = re.compile(r'<h2 class="pdp-link">\s*<a class="link"[^>]*>(.*?)</a>', re.S)
_PRICE = re.compile(r'<span class="value" content="([\d.,]+)"')
_LINK = re.compile(r'<a href="(/[^"#?]+-\d{6,20}\.html)"')
_SWATCH = re.compile(r'<a class="[^"]*tc-swatch-color"[^>]*data-href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_SWATCH_MODEL = re.compile(r"^/([a-z0-9-]+?)-(BNB[0-9A-Z]+)\.html\?dwvar_[0-9A-Z]+_color=(\d+)")
_SWATCH_PID = re.compile(r"/([a-z0-9-]+)-vue\d+-(\d{6,20})\.(?:jpg|png|webp)")
_TITLE = re.compile(r'title="([^"]*)"')
_FRONT = re.compile(r"-vue3-\d+\.(?:jpg|png|webp)", re.IGNORECASE)
_TAIL = re.compile(r"\s+(homme|hommes|mixte)\s*$", re.IGNORECASE)


def product_url(path: str) -> str:
    return ORIGIN + path if path.startswith("/") else path


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", norm(text))


def split_color(full: str, model: str) -> tuple[str, str]:
    """(nombre del modelo, color) de un nombre con el color dentro: «Polo droit manches longues en coton
    vert kaki homme» y el modelo «polo-droit-manches-longues-en-coton-homme» -> («Polo droit manches
    longues en coton», «vert kaki»). Si el nombre no empieza por el modelo, (el nombre, "")."""
    full = _TAIL.sub("", " ".join(html.unescape(full or "").split()))
    wanted = [w for w in _words(model) if w not in ("homme", "hommes", "mixte")]
    words = full.split(" ")
    at = 0
    for index, word in enumerate(words):
        if wanted and at >= len(wanted):
            return " ".join(words[:index]), " ".join(words[index:])
        parts = _words(word)
        if not parts:
            continue
        if parts != wanted[at:at + len(parts)]:
            return full, ""
        at += len(parts)
    return full, ""


def swatches(chunk: str) -> tuple[str, list[dict]]:
    """(modelo en la dirección, colores del producto: [{"pid", "code", "name"}]) de los circulitos de un producto."""
    model, colors = "", []
    for href, inner in _SWATCH.findall(chunk):
        match = _SWATCH_MODEL.search(html.unescape(href))
        pid = _SWATCH_PID.search(inner)
        if not match or not pid or any(c["pid"] == pid.group(2) for c in colors):
            continue
        model = model or match.group(1)
        titles = [t for t in _TITLE.findall(inner) if t and t != "null"]
        colour = split_color(html.unescape(titles[0]), match.group(1))[1] if titles else ""
        # Su página: el nombre de su foto sin la vista, como los enlaces de la web («…-ecru-homme-<pid>.html»).
        colors.append({"pid": pid.group(2), "code": match.group(3), "name": colour,
                       "url": f"{ORIGIN}/{pid.group(1)}-{pid.group(2)}.html"})
    return model, colors


def parse_grid(page: str, section: str) -> list[ShopProduct]:
    """De la rejilla de `Search-UpdateGrid` a productos, cada uno en su color."""
    default = SITE.categories.get(section, (None, None, None, None))[3]
    found: list[ShopProduct] = []
    for pid, chunk in tiles(page):
        tag = _TAGCO.search(chunk)
        try:
            tagco = json.loads(html.unescape(tag.group(1))) if tag else {}
        except ValueError:
            tagco = {}
        name = _NAME.search(chunk)
        price = _PRICE.search(chunk)
        link = _LINK.search(chunk)
        model, colors = swatches(chunk)
        full = html.unescape(name.group(1)) if name else ""
        shown, colour = split_color(full, model) if model else (_TAIL.sub("", " ".join(full.split())), "")
        own = next((c["name"] for c in colors if c["pid"] == pid), "")
        product = make_product(
            SITE, pid=pid, name=sentence_case(shown) if shown.isupper() else shown,
            price=cents(price.group(1)) if price else cents(tagco.get("product_unitprice_ati")),
            url=product_url(link.group(1)) if link else f"{ORIGIN}/p-{pid}.html", section=section,
            store_color=sentence_case(own or colour), default_type=default,
            extra={"colors": [{k: c[k] for k in ("pid", "name", "url")} for c in colors][:12]} if len(colors) > 1 else None,
        )
        if product is not None:
            found.append(product)
    return found


def _photo(path: str) -> str:
    """La foto en su tamaño grande: la ficha da la ruta de `demandware.static`; se pide por su CDN de fotos."""
    path = path.split("?")[0]
    if path.startswith(IMAGES):
        return f"{path}?{PHOTO}"
    if path.startswith(ORIGIN):
        path = path[len(ORIGIN):]
    return f"{IMAGES}{path}?{PHOTO}"


def parse_variation(product: dict, store_data: dict | None = None) -> ShopDetail:
    """De `Product-Variation` (su `product`) a la ficha de ese color. Los otros colores, de los que dejó la
    rejilla (con su pid exacto) y, si no, de los de la ficha (mismo modelo: el pid cambia en el color)."""
    store_data = store_data or {}
    pid = str(product.get("id") or store_data.get("pid") or "")
    images = [str((i or {}).get("url") or "") for i in (product.get("images") or {}).get("large") or []]
    images = [i for i in images if i]
    front = next((i for i in images if _FRONT.search(i.split("?")[0])), None)
    photos, model = ([_photo(front)], False) if front else (([_photo(images[0])], True) if images else ([], False))
    values = color_values(product)
    selected = next((v for v in values if str(v.get("selected")).lower() == "true"), values[0] if values else {})
    colour = sentence_case(" ".join(str(selected.get("displayValue") or "").split()))
    siblings = []
    for color in store_data.get("colors") or []:
        other = str((color or {}).get("pid") or "")
        if other.isdigit() and not any(s["product_ref"] == f"bonobo:{other}" for s in siblings):
            url = str(color.get("url") or "") or f"{ORIGIN}/p-{other}.html"
            siblings.append({"product_ref": f"bonobo:{other}", "name": sentence_case(color.get("name") or ""),
                             "hex": None, "url": url, "store_data": {"pid": other, "url": url}})
    if not siblings and len(values) > 1 and len(pid) > 4:
        for value in values:
            code = str(value.get("id") or "")
            if not code.isdigit() or len(code) > 4 or not value.get("selectable"):
                continue
            other = pid[:-4] + code.zfill(4)
            # Su enlace: el de este color con el otro elegido, como hace la propia ficha al tocar el circulito.
            base = str(store_data.get("url") or product.get("productUrl") or "").split("?")[0]
            url = f"{product_url(base)}?dwvar_{pid}_color={code}" if base else f"{ORIGIN}/p-{other}.html"
            siblings.append({"product_ref": f"bonobo:{other}", "name": sentence_case(str(value.get("displayValue") or "")),
                             "hex": None, "url": url, "store_data": {"pid": other, "url": url}})
    for sibling in siblings:  # el propio, con su enlace de verdad
        if sibling["product_ref"] == f"bonobo:{pid}" and store_data.get("url"):
            sibling["url"] = sibling["store_data"]["url"] = store_data["url"]
    blocks = {str((b or {}).get("type")): str((b or {}).get("content") or "") for b in product.get("descriptionBlocks") or []}
    composition = blocks.get("materialAndcares", "")
    composition_part = re.search(r'<div class="product-composition".*?</div>', composition, re.S)
    composition = text_of(composition_part.group() if composition_part else "")
    # «Composition : Tissu principal : 100% POLYESTER Dont : …»: lo que va detrás de «Dont» es un detalle.
    composition = re.sub(r"^Composition\s*:\s*", "", composition).split(" Dont :")[0].strip()
    description = text_of(blocks.get("descriptionAndDetails", "") or str(product.get("longDescription") or ""))
    sales = ((product.get("price") or {}).get("sales") or {}).get("value")
    return ShopDetail(
        price_cents=cents(sales),
        old_price_cents=list_price(product),
        old_price_known=True,
        sizes=sizes_of(product),
        photo_urls=photos,
        description=description[:400],
        composition=composition[:300],
        siblings=sorted(siblings, key=lambda s: s["product_ref"]) if len(siblings) > 1 else [],
        store_color=colour,
        store_data={"model_photo": True} if model else {},
    )


class BonoboConnector(SfraConnector):
    def __init__(self):
        # No se sabe qué día saca novedades: los viernes (reparto de noches, ver shops/__init__.py).
        super().__init__(SITE, refresh_weekday=4)

    def parse_grid(self, page: str, section: str) -> list[ShopProduct]:
        return parse_grid(page, section)

    def parse_variation(self, data: dict, store_data: dict) -> ShopDetail | None:
        return parse_variation(data, store_data)

    def download(self, url: str) -> bytes:
        # Sus fotos tampoco responden a un cliente normal: se abren en la propia sesión del navegador.
        return browser.require(self.key).image(self.key, url)
