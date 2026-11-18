"""Conector de Pull&Bear (Francia, sección de hombre). Se lee con navegador: ver inditex.py y browser.py.

Las secciones, de su menú (`/api/storefront/1/stores/24009401/menu`, 18-11-2026): la ruta es la de su
«Tout afficher» (`<keyword>-n<seoId>`). Fotos de producto en la ropa: `a6m` delante y `a20m` detrás
(sobre fondo gris); `c1` y `z1` son la de delante recortada, por si faltara la `a6m`. En el calzado:
`z0m` lateral, `a2m` el par en tres cuartos y `a3m` desde atrás.
"""
from .inditex import InditexConnector, InditexSite

SITE = InditexSite(
    key="pullandbear",
    name="Pull&Bear",
    origin="https://www.pullandbear.com",
    path="/fr",
    store_id=24009401,
    catalog_id=20309459,
    media="https://static.pullandbear.net/assets/public",
    views=(("a6m", "c1", "z1"), ("a20m",)),
    shoe_views=(("z0m", "c1"), ("a2m", "z1m"), ("a3m", "z2m")),
    color_param="cS",
    bundle_param="pelement",
    categories={
        "t-shirts-n6323": ("Camisetas", "/homme/vetements/t-shirts-n6323", "camiseta"),
        "polos-n6371": ("Polos", "/homme/vetements/t-shirts/polos-n6371", "polo"),
        "chemises-n6313": ("Camisas", "/homme/vetements/chemises-n6313", "camisa"),
        "sweats-n6382": ("Sudaderas", "/homme/vetements/sweats-n6382", "sudadera"),
        "pulls-n6378": ("Punto", "/homme/vetements/maille/pulls-n6378", "jersey"),
        "blousons-n6335": ("Chaquetas", "/homme/vetements/blousons-n6335", "chaqueta"),
        "surchemises-n6994": ("Sobrecamisas", "/homme/vetements/chemises/surchemises-n6994", "sobrecamisa"),
        "pantalons-n6363": ("Pantalones", "/homme/vetements/pantalons-n6363", "pantalón"),
        "jeans-n6347": ("Vaqueros", "/homme/vetements/jeans-n6347", "vaquero"),
        "bermudas-n6308": ("Bermudas", "/homme/vetements/bermudas-n6308", "pantalón corto"),
        "baskets-n6874": ("Zapatillas", "/homme/chaussures/baskets-n6874", "zapatillas"),
    },
)


class PullAndBearConnector(InditexConnector):
    def __init__(self):
        # No se sabe qué día saca novedades: se consulta los lunes (decisión del usuario, 18-11-2026).
        super().__init__(SITE, refresh_weekday=0)
