"""Conector de Lefties (Francia, sección de hombre). Se lee con navegador: ver inditex.py y browser.py.

Investigado el 18-11-2026 (Chromium de serie con ventana, sin bloqueos; intersticial de Akamai que se
resuelve solo). La página de cada sección pide ella sola su categoría y sus fichas, como Bershka.

- Secciones del menú `/api/storefront/1/stores/94009001/menu` (nodo `LEFTIES_MAN`): la ruta es
  `/fr/homme/vêtements/<nombre>-c<id>.html`. Comprobadas en sus propios enlaces todas menos la de
  Zapatillas (`/fr/homme/chaussures/baskets-c<id>.html`, deducida de la de Barefoot). Lleva además el id
  de categoría por si la página no la pidiera. Las secciones se solapan mucho (Camisas y Sobrecamisas,
  Polos y Sudaderas): lo repetido se guarda una vez. Chinos va dentro de Pantalones.
- Fotos de producto en la ropa: `p1` delante sin modelo sobre blanco (`a6` suele ser la misma). No hay
  espalda sin modelo. En el calzado: `a1` lateral, `a2` el par en tres cuartos y `a3` desde arriba.
- Enlace estilo Bershka, pero con el id del producto de dentro (`-c0p<id>.html?colorId=…`): es el que
  abre la ficha buena (comprobado); con el del «bundle» exterior no se comprobó.
- Los nombres vienen a veces en MAYÚSCULAS («BASKET COMBINÉE»): se pasan a formato de frase.
"""
from .inditex import InditexConnector, InditexSite

_V = "/homme/v%C3%AAtements"  # «vêtements»

SITE = InditexSite(
    key="lefties",
    name="Lefties",
    origin="https://www.lefties.com",
    path="/fr",
    store_id=94009001,
    catalog_id=90009053,
    media="https://static.lefties.com/assets/public",
    views=(("p1", "a6"),),
    shoe_views=(("a1", "p1"), ("a2",), ("a3",)),
    color_param="colorId",
    bundle_param=None,
    link_id="summary",
    categories={
        "t-shirts-c1030267569": ("Camisetas", f"{_V}/t-shirts-c1030267569.html", "camiseta", 1030267569),
        "polos-c1030267602": ("Polos", f"{_V}/polos-c1030267602.html", "polo", 1030267602),
        "chemises-c1030267570": ("Camisas", f"{_V}/chemises-c1030267570.html", "camisa", 1030267570),
        "surchemises-c1030691697": ("Sobrecamisas", f"{_V}/surchemises-c1030691697.html", "sobrecamisa", 1030691697),
        "sweats-c1030267572": ("Sudaderas", f"{_V}/sweats-%7C-hoodies-c1030267572.html", "sudadera", 1030267572),
        "pulls-c1030267573": ("Punto", f"{_V}/pulls-%7C-gilets-c1030267573.html", "jersey", 1030267573),
        "vestes-c1030267577": ("Chaquetas y abrigos", f"{_V}/vestes-%7C-manteaux-c1030267577.html", "chaqueta",
                               1030267577),
        "pantalons-c1030267575": ("Pantalones", f"{_V}/pantalons-c1030267575.html", "pantalón", 1030267575),
        "jeans-c1030267574": ("Vaqueros", f"{_V}/jeans-c1030267574.html", "vaquero", 1030267574),
        "bermudas-c1030267576": ("Bermudas", f"{_V}/bermudas-%7C-shorts-c1030267576.html", "pantalón corto",
                                 1030267576),
        "baskets-c1030272289": ("Zapatillas", "/homme/chaussures/baskets-c1030272289.html", "zapatillas", 1030272289),
    },
)


class LeftiesConnector(InditexConnector):
    def __init__(self):
        # No se sabe qué día saca novedades: los sábados (reparto de noches, ver shops/__init__.py).
        super().__init__(SITE, refresh_weekday=5)
