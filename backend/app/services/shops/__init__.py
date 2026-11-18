"""Tiendas de las que la pestaña Compras trae novedades. Una entrada por conector."""
from .base import ShopConnector, ShopDetail, ShopError, ShopProduct
from .zara import ZaraConnector

CONNECTORS: dict[str, ShopConnector] = {
    "zara": ZaraConnector(),
}

__all__ = ["CONNECTORS", "ShopConnector", "ShopDetail", "ShopError", "ShopProduct"]
