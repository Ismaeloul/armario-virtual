"""Tiendas de las que la pestaña Compras trae novedades. Una entrada por conector.

Reparto de noches (18-11-2026). Cada tienda se consulta un día fijo a la semana (`refresh_weekday`), a la
hora de la noche, y las de una misma noche van una detrás de otra. Con diez tiendas ya no hay un día para
cada una, así que el reparto busca que cada noche haya como mucho DOS tiendas y como mucho UNA «pesada»
(las de Inditex con navegador: muchas secciones y muchas fichas). Además, el bucle de la noche lo hace
cumplir aunque coincidan más (recién activadas a la vez, una que falló y se repite): las que no caben
pasan a la noche siguiente (ver `shopping.tonight`).

    Lun  Pull&Bear (pesada)       + Jack & Jones
    Mar  Massimo Dutti (pesada)   + Courir
    Mié  JD Sports (navegador, ligera: solo zapatillas) + Carhartt WIP
    Jue  Bershka (pesada)         + Nike
    Vie  Zara (el día después de sus novedades)
    Sáb  Lefties (pesada)
    Dom  libre

Huecos para las que vienen (Snipes, Size?, Foot Locker, Jules, Bonobo, Uniqlo, Mango, Weekday, H&M,
COS): con dos por noche quedan cuatro sitios (Vie, Sáb y dos el Dom) y una pesada el Vie y el Dom. Con las
veinte hará falta subir a tres por noche (`ARMARIO_SHOP_STORES_PER_NIGHT=3`: 21 sitios). Pero por la
investigación, de las nuevas irían con navegador pesado Jules, Bonobo, H&M, COS y Weekday: nueve pesadas
en total para siete noches. O se deja que alguna noche lleve dos (`ARMARIO_SHOP_HEAVY_PER_NIGHT=2`) o esas
pasarán a consultarse cada ocho o nueve días (el bucle las va corriendo solo). Las de zapatillas con
navegador (Snipes, Size?) serían ligeras, como JD Sports.
"""
from . import browser, crawl
from .base import BlockedError, BrowserUnavailable, NeedsBrowser, NotThisStore, SearchError, ShopConnector, ShopDetail
from .base import ShopError, ShopProduct
from .crawl import Cancelled, Partial
from .bershka import BershkaConnector
from .carhartt import CarharttConnector
from .courir import CourirConnector
from .jackjones import JackJonesConnector
from .jdsports import JDSportsConnector
from .lefties import LeftiesConnector
from .massimodutti import MassimoDuttiConnector
from .nike import NikeConnector
from .pullandbear import PullAndBearConnector
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
    "nike": NikeConnector(),  # solo zapatillas
    "jackjones": JackJonesConnector(),
    "carhartt": CarharttConnector(),
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


def cached_detail(key: str, store_data: dict):
    """La ficha de un producto sacada de lo que guardó el listado, sin volver a la tienda (Pull&Bear,
    Bershka, Massimo Dutti, Lefties y JD Sports la guardan; las demás no). None si no se puede."""
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
    "kinds", "needs_browser", "unavailable",
]
