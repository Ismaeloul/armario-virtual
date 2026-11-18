"""Tiendas de las que la pestaña Compras trae novedades. Una entrada por conector."""
from . import browser, crawl
from .base import BlockedError, BrowserUnavailable, NeedsBrowser, NotThisStore, SearchError, ShopConnector, ShopDetail
from .base import ShopError, ShopProduct
from .crawl import Cancelled, Partial
from .bershka import BershkaConnector
from .courir import CourirConnector
from .jdsports import JDSportsConnector
from .pullandbear import PullAndBearConnector
from .zara import ZaraConnector

# Todas arrancan desactivadas: el usuario las activa en la pestaña.
CONNECTORS: dict[str, ShopConnector] = {
    "zara": ZaraConnector(),
    "courir": CourirConnector(),
    # Estas tres solo se leen con un navegador de verdad (browser.py), en las consultas en segundo plano.
    "jdsports": JDSportsConnector(),
    "pullandbear": PullAndBearConnector(),
    "bershka": BershkaConnector(),
}


def needs_browser(key: str) -> bool:
    return bool(getattr(CONNECTORS.get(key), "needs_browser", False))


def unavailable(key: str) -> str | None:
    """Por qué no se puede consultar ahora una tienda en este equipo («No disponible: falta el
    navegador»), o None si se puede. Solo afecta a las que necesitan navegador."""
    return browser.missing() if needs_browser(key) else None


def cached_detail(key: str, store_data: dict):
    """La ficha de un producto sacada de lo que guardó el listado, sin volver a la tienda (Pull&Bear,
    Bershka y JD Sports la guardan; Zara y Courir no). None si no se puede."""
    make = getattr(CONNECTORS.get(key), "cached_detail", None)
    if make is None or not isinstance(store_data, dict):
        return None
    try:
        return make(store_data)
    except Exception:  # un `store_data` antiguo o raro: se pide a la tienda como siempre
        return None


__all__ = [
    "CONNECTORS", "BlockedError", "BrowserUnavailable", "Cancelled", "NeedsBrowser", "NotThisStore", "Partial",
    "SearchError", "ShopConnector", "ShopDetail", "ShopError", "ShopProduct", "cached_detail", "crawl",
    "needs_browser", "unavailable",
]
