"""Tiendas de las que la pestaña Compras trae novedades. Una entrada por conector.

Reparto de noches (18-11-2026). Cada tienda se consulta un día fijo a la semana (`refresh_weekday`), a la
hora de la noche, y las de una misma noche van una detrás de otra, de madrugada (nadie usa el Umbrel a esa
hora: que tarde una o dos horas no importa). Con veinte tiendas, cada noche lleva como mucho TRES tiendas y
como mucho DOS «pesadas» (las de navegador con muchas secciones o muchas páginas: las de Inditex, Jules,
Bonobo, Uniqlo, Mango, H&M, COS y Weekday). Las de zapatillas con navegador (JD Sports, Snipes, size? y
Nike) son ligeras: una o dos secciones. Además, el bucle de la noche lo hace cumplir aunque coincidan más (recién
activadas a la vez, una que falló y se repite): las que no caben pasan a la noche siguiente (ver
`shopping.tonight`; los topes, `ARMARIO_SHOP_STORES_PER_NIGHT` y `ARMARIO_SHOP_HEAVY_PER_NIGHT`).

    Lun  Pull&Bear (pesada)       + Jack & Jones                  + Uniqlo (pesada)
    Mar  Massimo Dutti (pesada)   + Courir                        + Mango (pesada)
    Mié  Jules (pesada)           + JD Sports + Carhartt WIP
    Jue  Bershka (pesada)         + Nike                          + H&M (pesada)
    Vie  Zara (el día después de sus novedades) + Bonobo (pesada) + Foot Locker
    Sáb  Lefties (pesada)         + Snipes                        + COS (pesada)
    Dom  size?                    + Weekday (pesada)              (y un sitio libre)

Veinte tiendas en 21 sitios y once pesadas en 14, sin pasar de los topes ninguna noche. Uniqlo, Mango, H&M,
COS y Weekday se leen solo por su listado, con navegador y sin abrir nunca una ficha (ver listing.py).
"""
from . import browser, crawl
from .base import BlockedError, BrowserUnavailable, NeedsBrowser, NotThisStore, SearchError, ShopConnector, ShopDetail
from .base import ShopError, ShopProduct
from .crawl import Cancelled, Partial
from .base import maker_key
from .bershka import BershkaConnector
from .bonobo import BonoboConnector
from .carhartt import CarharttConnector
from .cos import COSConnector
from .courir import CourirConnector
from .footlocker import FootLockerConnector
from .hm import HMConnector
from .jackjones import JackJonesConnector
from .jdsports import JDSportsConnector
from .jules import JulesConnector
from .lefties import LeftiesConnector
from .mango import MangoConnector
from .massimodutti import MassimoDuttiConnector
from .nike import NikeConnector
from .pullandbear import PullAndBearConnector
from .sizeofficial import SizeConnector
from .snipes import SnipesConnector
from .uniqlo import UniqloConnector
from .weekday import WeekdayConnector
from .zara import ZaraConnector
from ... import catalog

# Todas arrancan desactivadas: el usuario las activa en la pestaña. El orden es el del panel «Tiendas».
CONNECTORS: dict[str, ShopConnector] = {
    "zara": ZaraConnector(),
    "courir": CourirConnector(),
    # Estas tres solo se leen con un navegador de verdad (browser.py), en las consultas en segundo plano.
    "jdsports": JDSportsConnector(),
    "pullandbear": PullAndBearConnector(),
    "bershka": BershkaConnector(),
    "massimodutti": MassimoDuttiConnector(),  # navegador
    "lefties": LeftiesConnector(),  # navegador
    "nike": NikeConnector(),  # solo zapatillas; navegador (escucha lo que pide la página al bajar)
    "jackjones": JackJonesConnector(),
    "carhartt": CarharttConnector(),
    # Zapatillas de muchas marcas: Snipes (listado con navegador, ficha sin él), size? (con navegador) y Foot
    # Locker (sin navegador: con él, su antibots niega la API de la web).
    "snipes": SnipesConnector(),
    "size": SizeConnector(),
    "footlocker": FootLockerConnector(),
    "jules": JulesConnector(),  # navegador
    "bonobo": BonoboConnector(),  # navegador (también para las fotos)
    # Solo por su listado, con navegador y sin abrir nunca una ficha (listing.py). H&M, COS, Uniqlo y Mango,
    # sin tallas en el listado.
    "uniqlo": UniqloConnector(),
    "mango": MangoConnector(),
    "hm": HMConnector(),
    "cos": COSConnector(),
    "weekday": WeekdayConnector(),
}


def needs_browser(key: str) -> bool:
    return bool(getattr(CONNECTORS.get(key), "needs_browser", False))


def heavy(key: str) -> bool:
    """¿Es de las pesadas para el reparto de noches? Por defecto, las de navegador."""
    connector = CONNECTORS.get(key)
    return bool(getattr(connector, "heavy", getattr(connector, "needs_browser", False)))


def kinds(key: str, sections: list[str] | None = None) -> list[str]:
    """Las clases de prenda (nuestras categorías: «parte_superior», «calzado»…) que trae la tienda en
    esas secciones (todas, si no se dicen), en el orden del catálogo. Sin `section_types`, todas."""
    connector = CONNECTORS.get(key)
    types = getattr(connector, "section_types", None)
    if not types:
        return list(catalog.CATEGORIES)
    wanted = types if sections is None else {slug: types[slug] for slug in sections if slug in types}
    found = {catalog.category_of(t) for t in wanted.values() if t}
    return [c for c in catalog.CATEGORIES if c in found]


def unavailable(key: str) -> str | None:
    """Por qué no se puede consultar ahora una tienda en este equipo («No disponible: falta el
    navegador»), o None si se puede. Solo afecta a las que necesitan navegador."""
    return browser.missing() if needs_browser(key) else None


def maker_code(key: str, store_data: dict) -> str | None:
    """El código de fabricante de un producto, como clave para reconocer la misma zapatilla (modelo y
    color) en tiendas distintas («CW2288111»). None si la tienda no lo dice o aún no se ha leído su ficha."""
    make = getattr(CONNECTORS.get(key), "maker_code", None)
    if make is None or not isinstance(store_data, dict):
        return None
    try:
        return maker_key(make(store_data))
    except Exception:  # un `store_data` antiguo o raro no puede tumbar nada
        return None


def cached_detail(key: str, store_data: dict):
    """La ficha de un producto sacada de lo que guardó el listado, sin volver a la tienda (Pull&Bear,
    Bershka, Massimo Dutti, Lefties, JD Sports, las de solo listado y, de día, Nike). None si no se puede."""
    make = getattr(CONNECTORS.get(key), "cached_detail", None)
    if make is None or not isinstance(store_data, dict):
        return None
    try:
        return make(store_data)
    except Exception:  # un `store_data` antiguo o raro: se pide a la tienda como siempre
        return None


__all__ = [
    "CONNECTORS", "BlockedError", "BrowserUnavailable", "Cancelled", "NeedsBrowser", "NotThisStore", "Partial",
    "SearchError", "ShopConnector", "ShopDetail", "ShopError", "ShopProduct", "cached_detail", "crawl", "heavy",
    "kinds", "maker_code", "maker_key", "needs_browser", "unavailable",
]
