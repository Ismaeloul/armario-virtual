"""Tiendas de las que la pestaña Compras trae novedades. Una entrada por conector."""
from .base import NotThisStore, SearchError, ShopConnector, ShopDetail, ShopError, ShopProduct
from .courir import CourirConnector
from .jdsports import JDSportsConnector
from .zara import ZaraConnector

# Todas arrancan desactivadas: el usuario las activa en la pestaña.
CONNECTORS: dict[str, ShopConnector] = {
    "zara": ZaraConnector(),
    "courir": CourirConnector(),
    "jdsports": JDSportsConnector(),
}

__all__ = [
    "CONNECTORS", "NotThisStore", "SearchError", "ShopConnector", "ShopDetail", "ShopError", "ShopProduct",
]
