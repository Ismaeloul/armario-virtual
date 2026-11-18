"""Interfaz común de los conectores de tiendas (Fase 4, Compras).

Un conector sabe leer el catálogo de UNA tienda y devolverlo normalizado: nombre, precio, enlace y
una estimación sin IA de nuestros campos cerrados (tipo, color, estampado, estilo y temporada).
No compra nada ni toca datos de pago: la app solo enlaza a la página del producto.

Para añadir una tienda (Pull&Bear, Bershka…): una clase con esta forma en su propio archivo y una
línea en `CONNECTORS` (services/shops/__init__.py).
"""
import re
from dataclasses import dataclass, field
from typing import Protocol


def maker_key(code) -> str | None:
    """El código de fabricante de una zapatilla («CW2288-111», «IF6490», «1203A739-200») como clave para
    reconocer el mismo modelo y color en tiendas distintas: en mayúsculas y sin separadores
    («CW2288111»). None si no tiene forma de código (muy corto, sin cifras o sin letras ni guion)."""
    text = re.sub(r"[^A-Z0-9]", "", str(code or "").upper())
    if not 5 <= len(text) <= 20 or not re.search(r"\d", text):
        return None
    if not re.search(r"[A-Z]", text) and "-" not in str(code):
        return None  # solo cifras y sin guion: un número interno de la tienda, no un código de modelo
    return text


def old_price(current, before) -> int | None:
    """El precio de antes de una oferta, en céntimos, solo si la tienda lo da y es MAYOR que el de ahora
    (si no, no es una oferta). Nunca se deduce de lo apuntado otro día: sale de lo que dice la tienda."""
    if not isinstance(current, int) or isinstance(current, bool) or current <= 0:
        return None
    if not isinstance(before, int) or isinstance(before, bool):
        return None
    return before if before > current else None


class ShopError(Exception):
    """La tienda no respondió como se esperaba. El mensaje se enseña tal cual en el panel «Tiendas»,
    así que va en claro: «HTTP 403», «tiempo agotado», «la respuesta no era la esperada»."""


class BlockedError(ShopError):
    """La tienda ha bloqueado el acceso o pide un captcha. No se rodea ni se insiste: se para con esa
    tienda y no se le vuelve a preguntar hasta el día siguiente. El mensaje va en claro para el panel."""


class BrowserUnavailable(ShopError):
    """El navegador de este equipo no está o no arranca (falta Chromium, falta la pantalla virtual…).
    La tienda no se ha llegado a tocar: no es un bloqueo."""


class NeedsBrowser(ShopError):
    """Esto solo se puede pedir con el navegador, y el navegador solo se abre en las consultas en
    segundo plano (no dentro de una petición HTTP). No es un fallo de la tienda: el mensaje ya va
    escrito para el usuario."""


class SearchError(ShopError):
    """El buscador no puede dar nada con lo que se le ha pedido (la referencia no existe, no tiene
    forma de referencia…). No es un fallo de la tienda, y el mensaje ya va escrito para el usuario."""


class NotThisStore(SearchError):
    """Lo que se busca es un enlace de otra tienda: este conector no tiene nada que decir."""


@dataclass
class ShopProduct:
    """Un producto del listado de una categoría, ya normalizado."""

    store: str
    product_ref: str  # único por producto + color, con la tienda delante ("zara:05854122-800")
    name: str  # en formato de frase, no en MAYÚSCULAS
    price_cents: int
    url: str  # la página del producto, para el usuario
    store_color: str  # el color tal como lo llama la tienda
    section: str  # la categoría de la tienda de la que salió (slug)
    # Estimación sin IA de nuestros campos cerrados.
    type: str
    category: str
    color: str
    pattern: str
    style: str
    season: str
    details: str = ""  # texto libre (nombre, pistas de la categoría) para las reglas que leen palabras
    brand: str = ""  # la marca del producto, si la tienda vende varias (Nike, Adidas…); "" si es la propia tienda
    # Lo que el conector necesita para volver a pedir el detalle de este producto más adelante.
    store_data: dict = field(default_factory=dict)
    # Ofertas: el precio de antes (tachado) si la TIENDA dice que está rebajado; None si no lo está o no lo
    # dice. `old_price_known`: este listado sabe decir si hay rebaja (con None, es que no la hay). Si no lo
    # sabe (False), un None no quita la rebaja que dijo otra fuente para ese mismo precio (ver `old_price`).
    old_price_cents: int | None = None
    old_price_known: bool = False


@dataclass
class ShopDetail:
    """La ficha de un producto: lo que no viene en el listado."""

    price_cents: int | None
    sizes: list[dict]  # [{"name": "M", "in_stock": True}]
    # Fotos de producto sin modelo, en el orden de la prenda: delante, detrás, otra vista (en calzado:
    # lateral, tres cuartos o de frente, otra vista). Las tres primeras pasan al armario al comprarla;
    # una cuarta, si la hay, solo se ve en el visor.
    photo_urls: list[str]
    description: str = ""
    color_hex: str | None = None
    composition: str = ""  # de qué está hecha, como lo dice la tienda («Exterior: 55% poliéster, 45% lana»)
    # Todos los colores en los que existe el producto, este incluido, y solo los que tienen foto de
    # producto: [{"product_ref", "name", "hex" (o None), "url", "store_data"}]. Cada color es un
    # producto aparte (su propio `product_ref`); `store_data` es lo que hace falta para pedir su ficha.
    # None si el conector no lo sabe.
    siblings: list[dict] | None = None
    # El nombre del color según la ficha, si el listado no lo traía (Courir): "" si no lo dice.
    store_color: str = ""
    # Datos que la ficha sabe y el listado no (el código de fabricante en Courir): se añaden a `store_data`.
    store_data: dict = field(default_factory=dict)
    # False si la página no dice qué tallas quedan (Nike: lo dice una API interna que no se llama). Entonces
    # el producto sale sin tallas y cuenta como disponible mientras la tienda lo venda (`sold_out`).
    stock_known: bool = True
    sold_out: bool = False
    # El precio de antes, si la tienda dice que está rebajado (como en ShopProduct). Solo cuenta junto a
    # `price_cents`: una ficha sin precio no dice nada del precio. `old_price_known`: esta ficha sabe decir
    # si hay rebaja (la de Courir o Carhartt WIP no: solo da el precio de ahora).
    old_price_cents: int | None = None
    old_price_known: bool = False

    @property
    def in_stock(self) -> bool:
        if not self.stock_known:
            return not self.sold_out
        return any(size["in_stock"] for size in self.sizes)


class ShopConnector(Protocol):
    key: str  # "zara"
    name: str  # "Zara": se enseña al usuario; es la marca de la prenda al comprarla si el producto no trae otra
    # Idioma de los nombres de la tienda ("fr", "es"…): lo que no está en español se traduce para enseñarlo.
    language: str
    categories: dict[str, str]  # slug de la tienda -> nombre para el usuario
    # Día de la semana en que se consulta (lunes = 0): el siguiente al que la tienda saca novedades.
    refresh_weekday: int
    # Opcional: True si la tienda solo se deja leer con un navegador de verdad (Pull&Bear, Bershka, JD Sports).
    # Esas solo hablan con la tienda en el hilo de las consultas (ver shops/browser.py).
    # needs_browser: bool
    # Opcional: si es de las «pesadas» para el reparto de noches (por defecto, las de navegador): de esas
    # se consulta como mucho una por noche (ver shopping.tonight). JD Sports, con navegador pero solo
    # unas pocas páginas de zapatillas, no lo es.
    # heavy: bool
    # Opcional: el tipo de prenda que trae cada sección ({"t-shirts-n6323": "camiseta"}), para saber qué
    # clase de ropa vende la tienda (el aviso de Descubrir no promete chaquetas de una tienda de zapatillas).
    # section_types: dict[str, str]

    # Opcional: secciones que ya están dentro de otras ({"nike": ("baskets",)}). Si las que la contienen
    # están activas y se han leído enteras, esta no se vuelve a recorrer.
    # covered_by: dict[str, tuple[str, ...]]

    def list_category(self, slug: str) -> list[ShopProduct]:
        """TODOS los productos de una categoría, página a página (ver crawl.py: antes de cada página
        `crawl.before_page()`, después `crawl.page_read(n)`, y los topes de `crawl.max_pages`). Lanza
        ShopError si la primera página falla, y `crawl.Partial` (con lo leído) si falla una siguiente."""

    # Opcional: def cached_detail(self, store_data: dict) -> ShopDetail | None
    #   La ficha sacada de lo que guardó el listado, sin volver a la tienda (fotos de su CDN incluidas).

    def detail(self, store_data: dict) -> ShopDetail | None:
        """La ficha de un producto. None si ya no existe en la tienda. Lanza ShopError si falla."""

    def download(self, url: str) -> bytes:
        """Los bytes de una foto. Lanza ShopError si falla."""

    def reference(self, store_data: dict) -> str | None:
        """La referencia del producto como la escribe la tienda («3918/300/800»), para enseñarla y
        copiarla. Es opcional: con un conector sin `reference`, la app no enseña referencia."""

    # Opcional: def maker_code(self, store_data: dict) -> str | None
    #   El código de fabricante (el de la caja: «CW2288-111»), si se sabe. Sirve para no proponer a la
    #   vez la misma zapatilla de dos tiendas y para el «También en» del visor (ver shopping).

    def search(self, query: str, limit: int) -> list[ShopProduct]:
        """El buscador: lo que el usuario escribe en un solo campo (una referencia, un enlace de
        producto o texto libre) -> productos, uno por color y como mucho `limit`. Lanza SearchError
        si no hay nada que enseñar (NotThisStore si es un enlace de otra tienda) y ShopError si la
        tienda falla. Es opcional: un conector sin `search` no entra en el buscador."""
