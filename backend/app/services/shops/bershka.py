"""Conector de Bershka (Francia, sección de hombre). Se lee con navegador: ver inditex.py y browser.py.

Las secciones, de su menú (`/api/storefront/1/stores/44009501/menu`, 18-11-2026): la ruta es
`<keyword>-n<seoId>.html`. Bershka no tiene sección de sobrecamisas (van en Camisas) y Camisetas trae
también los polos. Fotos de producto en la ropa: `a4o` delante y `b1` detrás (sobre fondo gris); `s1`
es la de delante sobre blanco, por si faltara la `a4o`. En el calzado: `a4o` lateral, `a3o` desde
atrás en tres cuartos y `a5o` desde arriba.
"""
from .inditex import InditexConnector, InditexSite

SITE = InditexSite(
    key="bershka",
    name="Bershka",
    origin="https://www.bershka.com",
    path="/fr",
    store_id=44009501,
    catalog_id=40259533,
    media="https://static.bershka.net/assets/public",
    views=(("a4o", "s1"), ("b1",)),
    shoe_views=(("a4o", "z1", "v1"), ("a3o",), ("a5o",)),
    color_param="colorId",
    bundle_param=None,
    categories={
        "t-shirts-n3294": ("Camisetas y polos", "/homme/vetements/t-shirts-n3294.html", "camiseta"),
        "polo-n3303": ("Polos", "/homme/vetements/t-shirts/polo-n3303.html", "polo"),
        "chemises-n3700": ("Camisas", "/homme/vetements/chemises-n3700.html", "camisa"),
        "sweats-n3714": ("Sudaderas", "/homme/vetements/sweats-avec-ou-sans-capuche-n3714.html", "sudadera"),
        "pulls-et-gilets-n3710": ("Punto", "/homme/vetements/pulls-et-gilets-n3710.html", "jersey"),
        "vestes-et-manteaux-n3668": ("Chaquetas y abrigos", "/homme/vetements/vestes-et-manteaux-n3668.html", "chaqueta"),
        "pantalons-n3288": ("Pantalones", "/homme/vetements/pantalons-n3288.html", "pantalón"),
        "jeans-n3676": ("Vaqueros", "/homme/vetements/jeans-n3676.html", "vaquero"),
        "shorts-n3705": ("Bermudas", "/homme/vetements/shorts-n3705.html", "pantalón corto"),
        "baskets-n6125": ("Zapatillas", "/homme/shoes/chaussures/baskets-n6125.html", "zapatillas"),
    },
)


class BershkaConnector(InditexConnector):
    def __init__(self):
        # Los viernes ya es Zara: Bershka se consulta los jueves (decisión del usuario, 18-11-2026).
        super().__init__(SITE, refresh_weekday=3)
