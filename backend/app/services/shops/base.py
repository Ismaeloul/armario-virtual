"""Interfaz común de los conectores de tiendas (Fase 4, Compras).

Un conector sabe leer el catálogo de UNA tienda y devolverlo normalizado: nombre, precio, enlace y
una estimación sin IA de nuestros campos cerrados (tipo, color, estampado, estilo y temporada).
No compra nada ni toca datos de pago: la app solo enlaza a la página del producto.

Para añadir una tienda (Pull&Bear, Bershka…): una clase con esta forma en su propio archivo y una
línea en `CONNECTORS` (services/shops/__init__.py).
"""
from dataclasses import dataclass, field
from typing import Protocol


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

    @property
    def in_stock(self) -> bool:
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

    def list_category(self, slug: str) -> list[ShopProduct]:
        """Los productos de una categoría. Lanza ShopError si la tienda no responde bien."""

    def detail(self, store_data: dict) -> ShopDetail | None:
        """La ficha de un producto. None si ya no existe en la tienda. Lanza ShopError si falla."""

    def download(self, url: str) -> bytes:
        """Los bytes de una foto. Lanza ShopError si falla."""

    def reference(self, store_data: dict) -> str | None:
        """La referencia del producto como la escribe la tienda («3918/300/800»), para enseñarla y
        copiarla. Es opcional: con un conector sin `reference`, la app no enseña referencia."""

    def search(self, query: str, limit: int) -> list[ShopProduct]:
        """El buscador: lo que el usuario escribe en un solo campo (una referencia, un enlace de
        producto o texto libre) -> productos, uno por color y como mucho `limit`. Lanza SearchError
        si no hay nada que enseñar (NotThisStore si es un enlace de otra tienda) y ShopError si la
        tienda falla. Es opcional: un conector sin `search` no entra en el buscador."""
