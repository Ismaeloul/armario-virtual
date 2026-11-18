"""Conector de Massimo Dutti (Francia, sección de hombre). Se lee con navegador: ver inditex.py y browser.py.

Investigado el 18-11-2026 (Chromium de serie con ventana, sin bloqueos; la primera visita pasa por un
intersticial de Akamai que se resuelve solo). Diferencias con Pull&Bear:

- La página de una sección NO pide `category/<id>/product`: los ids van dentro del HTML. Solo pide la
  primera tanda de `productsArray`. Por eso cada sección lleva su id de categoría (sacado del menú
  `/api/storefront/1/stores/34009451/menu`, el del nodo «Tout voir») y la categoría se pide desde dentro de
  la página, con la misma dirección que usan las demás tiendas de Inditex (responde 200).
- Las rutas `-nXXXX` no son las de la web española: la portada de hombre es `/fr/homme-n1343`.
- No hay sección de sudaderas. Chinos va dentro de Pantalones. Calzado entero (zapatillas, zapatos y
  botas: el tipo sale del nombre), porque Baskets solo tiene media docena.
- Fotos de producto en la ropa: `o1` delante y `o3` detrás, sin modelo sobre blanco (`t1` es la de delante
  recortada, por si faltara). En el calzado: `o1` lateral, `o2` el par en tres cuartos y `o3` desde arriba.
  Comprobado a ojo en camisas, camisetas y una zapatilla; no en abrigos, punto ni pantalones.
- Enlace: `/fr/<productUrl>?pelement=<bundle>` como en sus listados; el color va en `colorId` (sin
  comprobar en la web: si no lo entiende, abre el color por defecto del producto).
"""
from .inditex import InditexConnector, InditexSite

SITE = InditexSite(
    key="massimodutti",
    name="Massimo Dutti",
    origin="https://www.massimodutti.com",
    path="/fr",
    store_id=34009451,
    catalog_id=30359524,
    media="https://static.massimodutti.net/assets/public",
    views=(("o1", "t1"), ("o3",)),
    shoe_views=(("o1", "t1"), ("o2",), ("o3",)),
    color_param="colorId",
    bundle_param="pelement",
    categories={
        "t-shirts-n1369": ("Camisetas", "/homme/t-shirts-n1369", "camiseta", 911158),
        "polos-n1407": ("Polos", "/homme/polos-n1407", "polo", 2030100),
        "chemises-n1356": ("Camisas", "/homme/chemises-n1356", "camisa", 680504),
        "overshirts-n4949": ("Sobrecamisas", "/men/overshirts/overshirts-n4949", "sobrecamisa", 2130124),
        "pulls-n1384": ("Punto", "/homme/pulls-n1384", "jersey", 1736768),
        "blousons-n1372": ("Chaquetas", "/homme/blousons-n1372", "chaqueta", 680512),
        "manteaux-n1344": ("Abrigos", "/homme/manteaux-n1344", "abrigo", 1150001),
        "puffer-jackets-n1801": ("Plumíferos", "/s/m-puffer-jackets-n1801", "abrigo", 2211472),
        "pantalons-n1399": ("Pantalones", "/homme/pantalons-n1399", "pantalón", 911182),
        "jeans-n1405": ("Vaqueros", "/homme/pantalons/jeans-n1405", "vaquero", 911172),
        "bermudas-n1401": ("Bermudas", "/homme/pantalons/bermudas-n1401", "pantalón corto", 2020002),
        "chaussures-n1420": ("Zapatos y zapatillas", "/homme/chaussures-n1420", "zapatillas", 2096279),
    },
)


class MassimoDuttiConnector(InditexConnector):
    def __init__(self):
        # No se sabe qué día saca novedades: los martes (reparto de noches, ver shops/__init__.py).
        super().__init__(SITE, refresh_weekday=1)
