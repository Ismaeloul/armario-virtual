"""Tiendas de las que la pestaña Compras trae novedades. Una entrada por conector."""
from .base import NotThisStore, SearchError, ShopConnector, ShopDetail, ShopError, ShopProduct
from .zara import ZaraConnector

CONNECTORS: dict[str, ShopConnector] = {
    "zara": ZaraConnector(),
}

__all__ = [
    "CONNECTORS", "NotThisStore", "SearchError", "ShopConnector", "ShopDetail", "ShopError", "ShopProduct",
]
