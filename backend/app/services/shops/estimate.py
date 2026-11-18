"""Estimación SIN IA de nuestros campos cerrados a partir de lo que dice la tienda.

Solo palabras del nombre, la categoría de la tienda y el color en texto: sirve para puntuar el
catálogo sin gastar el límite de Codex. La IA solo mira las fotos cuando el usuario compra la prenda.
"""
import re
import unicodedata

from ... import catalog


def norm(text: str | None) -> str:
    """Minúsculas y sin tildes, para buscar palabras."""
    text = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


def sentence_case(name: str) -> str:
    """«SOBRECAMISA BOXY FIT» -> «Sobrecamisa boxy fit»."""
    name = " ".join((name or "").split())
    return name[:1].upper() + name[1:].lower()


# Lo que no cabe en el armario (no hay tipo para ello): se descarta.
_NOT_A_GARMENT = re.compile(
    r"\b(calcetin|gorra|gorro|bufanda|cinturon|bolso|mochila|perfume|colonia|corbata|boxer|calzoncillo|"
    r"pijama|banador|guante|cartera|gafas|panuelo|rinonera|sombrero|llavero|slip)"
)

# Palabra del nombre -> tipo. Gana la que aparece antes en el nombre («POLO PUNTO» es un polo).
_TYPE_WORDS = [
    (r"sobrecamisas?", "sobrecamisa"),
    (r"camisetas?", "camiseta"),
    (r"camisas?", "camisa"),
    (r"polos?", "polo"),
    (r"sudaderas?|hoodie", "sudadera"),
    (r"jersey|jerseis|cardigan|sueter", "jersey"),
    (r"abrigo|gabardina|trench|parka|anorak|plumifero", "abrigo"),
    (r"cazadora|chaqueta|bomber|blazer|americana|chaleco", "chaqueta"),
    (r"bermudas?|shorts?", "pantalón corto"),
    (r"jeans?|vaqueros?", "vaquero"),
    (r"joggers?|chandal", "chándal"),
    (r"pantalon|pantalones", "pantalón"),
    (r"chinos?", "chino"),
    (r"zapatillas?|sneakers?|deportivas?", "zapatillas"),
    (r"botas?|botin|botines", "botas"),
    (r"zapatos?|mocasin|mocasines|nauticos?|sandalias?|alpargatas?|zuecos?", "zapatos"),
]
_TYPE_RE = [(re.compile(rf"\b(?:{words})\b"), garment_type) for words, garment_type in _TYPE_WORDS]


def estimate_type(name: str, default: str | None = None) -> str | None:
    """El tipo de prenda por las palabras del nombre; si no dice nada, el de la categoría de la tienda.

    None = no es algo que quepa en el armario (calcetines, gorras…) o no se sabe qué es.
    """
    text = norm(name)
    if _NOT_A_GARMENT.search(text):
        return None
    found = [(m.start(), garment_type) for rx, garment_type in _TYPE_RE if (m := rx.search(text))]
    garment_type = min(found)[1] if found else default
    if garment_type == "pantalón" or (garment_type == "vaquero" and not found):
        # «PANTALÓN CHINO», «PANTALÓN JOGGER», «PANTALÓN CORTO»: lo que manda es el apellido.
        if re.search(r"\b(cortos?|bermudas?|shorts?)\b", text):
            return "pantalón corto"
        if re.search(r"\bchinos?\b", text):
            return "chino"
        if re.search(r"\b(joggers?|jogging|chandal)\b", text):
            return "chándal"
        if re.search(r"\b(jeans?|vaqueros?|denim)\b", text):
            return "vaquero"
    return garment_type


# Texto de la tienda -> nuestra paleta. De lo más concreto a lo más general: «Rojo burgundy» es burdeos.
_COLOR_WORDS = [
    (r"multicolor|varios|combinad|estampad", "multicolor"),
    (r"blanco roto|blanco hueso|off white|crudo|ecru|hueso|marfil|nata|crema|tiza|mantequilla", "crudo"),
    (r"marino|navy|azul oscuro|azul noche|tinta", "azul marino"),
    (r"azul claro|azul cielo|azul palido|azul hielo|celeste", "celeste"),
    (r"oliva|khaki|kaki|caqui|militar|musgo", "verde oliva"),
    (r"burdeos|burgundy|granate|vino|berenjena", "burdeos"),
    (r"marron|chocolate|conac|tabaco|cuero|tostado|caramelo|camel|taupe|topo|moka|cafe|castano|avellana|cobre", "marrón"),
    (r"beige|arena|piedra|vison|nude", "beige"),
    (r"gris|antracita|plomo|plata|marengo|ceniza|humo|grafito|carbon", "gris"),
    (r"negro|black", "negro"),
    (r"blanco|white", "blanco"),
    (r"azul|indigo|anil|petroleo|denim|cobalto|turquesa", "azul"),
    (r"verde|verdos|botella|menta|esmeralda", "verde"),
    (r"rojo|rojiz|coral", "rojo"),
    (r"amarillo|mostaza|vainilla|lima|ocre", "amarillo"),
    (r"naranja|teja|terracota|ladrillo|oxido|calabaza", "naranja"),
    (r"rosa|fucsia|salmon|maquillaje", "rosa"),
    (r"morado|lila|malva|violeta|lavanda|purpura", "morado"),
]
_COLOR_RE = [(re.compile(words), color) for words, color in _COLOR_WORDS]


def _rgb(hex_color: str) -> tuple[int, ...]:
    return tuple(int(hex_color[i : i + 2], 16) for i in (1, 3, 5))


def nearest_color(hex_color: str | None) -> str | None:
    """El color de la paleta más parecido a un tono «#rrggbb» (sin contar multicolor)."""
    if not hex_color or not re.fullmatch(r"#[0-9a-fA-F]{6}", hex_color):
        return None
    tone = _rgb(hex_color)
    return min(
        (c for c in catalog.COLORS if c != "multicolor"),
        key=lambda c: sum((x - y) ** 2 for x, y in zip(tone, _rgb(catalog.COLOR_HEX[c]))),
    )


def estimate_color(store_color: str | None, hex_color: str | None = None) -> str:
    """Del texto de la tienda («Marino», «Khaki», «Gris vigoré») a nuestra paleta.

    Si el texto no dice nada conocido, el tono más cercano; sin tono, multicolor.
    """
    text = norm(store_color)
    for rx, color in _COLOR_RE:
        if rx.search(text):
            return color
    return nearest_color(hex_color) or "multicolor"


def estimate_pattern(name: str) -> str:
    text = norm(name)
    if re.search(r"\b(rayas?|listas?)\b", text):
        return "rayas"
    if re.search(r"\b(cuadros?|vichy|tartan)\b", text):
        return "cuadros"
    if re.search(r"color ?block|\bbloques?\b", text):
        return "bloques de color"
    if re.search(r"estampad|\bprint|grafic|ilustracion|\btexto\b|slogan|dibujo", text):
        return "gráfico"
    if re.search(r"\b(textura|texturizad[oa]|estructura|pana|borreguito|trenzad[oa]|canale)\b", text):
        return "texturizado"
    return "liso"


def estimate_style(name: str, garment_type: str) -> str:
    text = norm(name)
    if garment_type == "chándal" or re.search(r"tecnic|training|running|deportiv|athletic|\bsport", text):
        return "deportivo"
    if garment_type in ("camisa", "chino", "zapatos") or re.search(
        r"\b(traje|blazer|americana|vestir|sastre|oxford)\b", text
    ):
        return "smart casual"
    return "casual"


def estimate_season(name: str, garment_type: str) -> str:
    """La misma regla por tipo de prenda que sigue la IA (services/ai/base.py)."""
    text = norm(name)
    if garment_type in ("sudadera", "jersey", "abrigo", "botas"):
        return "invierno"
    if garment_type == "pantalón corto" or re.search(r"\b(lino|tirantes|sin mangas)\b", text):
        return "verano"
    if garment_type == "chaqueta" and re.search(r"acolchad|plumifer|puffer|borreg|\blana\b|sherpa|grues", text):
        return "invierno"
    if garment_type == "camisa" and "franela" in text:
        return "invierno"
    return "todo_el_ano"
