"""Conector de Mango (Francia, hombre). Se lee CON NAVEGADOR y solo por el listado (ver listing.py).

Investigado el 18-11-2026. Sus APIs respondían a un cliente normal, pero NO se llaman por nuestra cuenta
(decisión del proyecto). Se abre la página de la sección con el navegador de serie y se lee lo que ella misma
trae y pide:

- Las primeras tarjetas vienen dentro de la página (los datos de React Server Components, `self.__next_f`):
  cada una con el producto entero (nombre, colores con su tono, fotos) y sus precios.
- Las demás las pide la página al ir bajando: la ficha de cada producto a `online-orchestrator.mango.com/v4/
  products?…` y su precio a `…/v4/prices/products?…`. Se baja la página hasta el final, como con la rueda, y se
  ESCUCHAN esas respuestas, una vuelta cada vez, hasta que no llega nada nuevo (o el tope de páginas).
- Foto de producto sin modelo: la vista `B` (bodegón, sufijo `-900`). Los colores sin ella no se proponen.
- Sin tallas con stock (lo dice otra llamada que la página solo hace al pasar por encima): «Tallas: míralas en
  la tienda». Sin composición.
- La ficha de producto no se abre nunca (el 18-11-2026 su cortafuegos respondió 403 a un navegador en la ficha
  después de una ráfaga de peticiones de un agente).

SIN PROBAR DE VERDAD: el 18-11-2026 la web estaba bloqueando la IP de casa (429 y 403). Todo sale de lo que
se vio antes del bloqueo (`tests/fixtures/mango_*`).
"""
import json
import re
from urllib.parse import parse_qs, urlsplit

from . import browser, crawl
from .base import ShopError
from .listing import Entry, ListingConnector, euros, fix_text, hex_color, make_product

BASE = "https://shop.mango.com"
MEDIA = "https://media.mango.com"
PHOTO_WIDTH = 1280
FLIGHT = "() => (self.__next_f || []).map(x => typeof x[1] === 'string' ? x[1] : '').join('')"
ORCHESTRATOR = "online-orchestrator.mango.com/"
MORE_WAIT = 12.0
QUIET_TICKS = 8  # 2 s sin respuestas nuevas: la página ha terminado de pedir lo que se ve
_CARD = re.compile(r'\{"dataTestId":"plp\.product"')

# slug -> (nombre para el usuario, ruta, tipo por defecto)
SECTIONS = {
    "t-shirts": ("Camisetas", "/fr/fr/c/homme/t-shirts/05a59413", "camiseta"),
    "polos": ("Polos", "/fr/fr/c/homme/polos/cc35bd0a", "polo"),
    "chemises": ("Camisas", "/fr/fr/c/homme/chemises/85ceefeb", "camisa"),
    "surchemises": ("Sobrecamisas", "/fr/fr/c/homme/surchemises/41a897fb", "sobrecamisa"),
    "sweat": ("Sudaderas", "/fr/fr/c/homme/sweat/f0789c5b", "sudadera"),
    "pulls": ("Punto", "/fr/fr/c/homme/gilets-et-pull-overs/89e09112", "jersey"),
    "vestes": ("Chaquetas", "/fr/fr/c/homme/vestes/b5a3a3f6", "chaqueta"),
    "manteaux": ("Abrigos", "/fr/fr/c/homme/manteaux/3a5ade78", "abrigo"),
    "doudounes": ("Plumíferos y acolchados", "/fr/fr/c/homme/doudounes--vestes-matelassees/c7864171", "abrigo"),
    "pantalons": ("Pantalones", "/fr/fr/c/homme/pantalons/b126cc9c", "pantalón"),
    "jeans": ("Vaqueros", "/fr/fr/c/homme/jeans/2402cc2c", "vaquero"),
    "bermudas": ("Bermudas", "/fr/fr/c/homme/bermudas/b0828e10", "pantalón corto"),
    "chaussures": ("Calzado", "/fr/fr/c/homme/chaussures/474b3a4f", "zapatos"),
}


def is_product(url: str) -> bool:
    return ORCHESTRATOR in url and "/v4/products?" in url


def is_price(url: str) -> bool:
    return ORCHESTRATOR in url and "/v4/prices/products?" in url


def wanted(url: str) -> bool:
    return is_product(url) or is_price(url)


def product_id_of(url: str) -> str:
    return (parse_qs(urlsplit(url).query).get("productId") or [""])[0]


def parse_cards(flight: str) -> tuple[dict[str, dict], dict[str, dict]]:
    """Las tarjetas que la página trae dentro: ({id: producto}, {id: precios por color})."""
    products: dict[str, dict] = {}
    prices: dict[str, dict] = {}
    decoder = json.JSONDecoder()
    for match in _CARD.finditer(flight or ""):
        try:
            card, _end = decoder.raw_decode(flight, match.start())
        except ValueError:
            continue
        product = card.get("product")
        if not isinstance(product, dict) or not str(product.get("id") or "").isdigit():
            continue
        products.setdefault(str(product["id"]), product)
        if isinstance(card.get("prices"), dict):  # si no, es una referencia a la de otra tarjeta del mismo producto
            prices.setdefault(str(product["id"]), card["prices"])
    return products, prices


def color_price(prices: dict, color_id: str) -> int | None:
    """El precio de un color: el más bajo de los que diga (el rebajado, si lo hay)."""
    values = []

    def walk(value) -> None:
        if isinstance(value, dict):
            for key, inner in value.items():
                if key == "price":
                    values.append(euros(inner))
                else:
                    walk(inner)

    walk((prices or {}).get(color_id))
    values = [v for v in values if v]
    return min(values) if values else None


def _still_life(color: dict) -> str | None:
    for look in (color.get("looks") or {}).values():
        image = ((look or {}).get("images") or {}).get("B") or {}
        if image.get("img"):
            return f"{MEDIA}{image['img']}?wid={PHOTO_WIDTH}"
    return None


def entries(product: dict, prices: dict) -> list[Entry]:
    """Los colores con foto sin modelo (y precio) de un producto, cada uno como un producto aparte."""
    product_id = str((product or {}).get("id") or (product or {}).get("reference") or "")
    if not product_id.isdigit() or str(product.get("genderId") or "H").upper() not in ("H", "U"):
        return []
    page = str(product.get("url") or "")
    family = " ".join(str((f or {}).get("label") or "") for f in product.get("families") or [])
    colors = []
    for color in product.get("colors") or []:
        color_id = str((color or {}).get("id") or "")
        if color_id and _still_life(color):
            colors.append({"id": f"{product_id}-{color_id}", "name": color.get("label"), "hex": hex_color(color.get("rgb")),
                           "url": f"{BASE}{page}?c={color_id}"})
    found = []
    for color in product.get("colors") or []:
        color_id = str((color or {}).get("id") or "")
        photo = _still_life(color or {})
        if not color_id or not photo:
            continue
        found.append(Entry(
            id=f"{product_id}-{color_id}",
            name=fix_text(product.get("name")),
            price_cents=color_price(prices, color_id),
            url=f"{BASE}{page}?c={color_id}",
            color=fix_text(color.get("label")),
            hex=hex_color(color.get("rgb")),
            photos=[photo],
            sizes=None,  # el stock lo dice otra llamada que la página no hace al listar
            colors=colors,
            ref=str(product.get("reference") or product_id),
            hint=family,
        ))
    return found


def parse_products(products: dict[str, dict], prices: dict[str, dict], section: str) -> list:
    default = SECTIONS[section][2] if section in SECTIONS else None
    out, refs = [], set()
    for product_id, product in products.items():
        for found in entries(product, prices.get(product_id) or {}):
            item = make_product("mango", "Mango", found, section, default)
            if item and item.product_ref not in refs:
                refs.add(item.product_ref)
                out.append(item)
    return out


class MangoConnector(ListingConnector):
    key = "mango"
    name = "Mango"
    domain = "mango.com"
    # No se sabe qué día saca novedades: los martes (ver el reparto en shops/__init__.py).
    refresh_weekday = 1  # lunes = 0
    categories = {slug: label for slug, (label, _path, _type) in SECTIONS.items()}
    section_types = {slug: kind for slug, (_label, _path, kind) in SECTIONS.items()}

    def list_category(self, slug: str) -> list:
        """La sección: las tarjetas que trae la página y, bajando, lo que ella misma pide de las demás."""
        _label, path, _type = SECTIONS[slug]
        session = browser.require(self.key)
        products: dict[str, dict] = {}
        prices: dict[str, dict] = {}
        limit = max(1, crawl.max_pages(self.key))

        def take(responses) -> int:
            before = len(products) + len(prices)
            for response in responses:
                if response.status != 200 or not isinstance(response.data, dict):
                    continue
                product_id = product_id_of(response.url)
                if is_product(response.url):
                    product = response.data
                    key = str(product.get("id") or product_id)
                    if key.isdigit():
                        products.setdefault(key, product)
                elif product_id.isdigit():
                    prices.setdefault(product_id, response.data)
            return len(products) + len(prices) - before

        def quiet():
            """Listo cuando llevan un rato sin llegar respuestas nuevas (la página ya ha pedido lo que se ve)."""
            state = {"count": -1, "still": 0}

            def ready(urls) -> bool:
                if len(urls) == state["count"]:
                    state["still"] += 1
                else:
                    state["count"], state["still"] = len(urls), 0
                return state["count"] > 0 and state["still"] >= QUIET_TICKS

            return ready

        def read_cards() -> None:
            """Las tarjetas que trae la página dentro (se vuelven a mirar en cada vuelta: pueden llegar tarde)."""
            cards, card_prices = parse_cards(str(session.evaluate(self.key, FLIGHT) or ""))
            for product_id, product in cards.items():
                products.setdefault(product_id, product)
            for product_id, value in card_prices.items():
                prices.setdefault(product_id, value)

        crawl.before_page()
        # Al abrir, basta con el primer precio que pida: las primeras tarjetas ya vienen dentro de la página, y
        # lo demás llega al bajar.
        take(session.open(self.key, BASE + path, want=wanted, ready=lambda urls: any(map(is_price, urls)),
                          wait=MORE_WAIT))
        read_cards()
        crawl.page_read(len(products))
        try:
            for _round in range(1, limit):
                if len(products) >= crawl.max_products(self.key):
                    break
                crawl.before_page()
                count = len(products)
                new = take(session.more(self.key, want=wanted, ready=quiet(), wait=MORE_WAIT))
                read_cards()
                crawl.page_read(len(products) - count)
                if not new and len(products) == count:
                    break  # bajando ya no pide nada nuevo: es el final
        except ShopError as exc:
            found = parse_products(products, prices, slug)
            if not found:
                raise
            raise crawl.Partial(found, exc) from exc
        found = parse_products(products, prices, slug)
        if not found:
            raise ShopError("la respuesta no era la esperada (sin productos)")
        return found
