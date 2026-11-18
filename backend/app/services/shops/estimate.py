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


# Lo que no cabe en el armario (no hay tipo para ello): se descarta. En español, francés (las tiendas de
# Francia) e inglés (los nombres de las zapatillas).
_NOT_A_GARMENT = re.compile(
    r"\b(calcetin|gorra|gorro|bufanda|cinturon|bolso|mochila|perfume|colonia|corbata|boxer|calzoncillo|"
    r"pijama|banador|guante|cartera|gafas|panuelo|rinonera|sombrero|llavero|slip|"
    r"chaussette|casquette|bonnet|echarpe|ceinture|sacs?\b|sacoche|parfum|eau de toilette|cravate|"
    r"calecon|maillot de bain|gants?\b|portefeuille|lunettes|porte-cles|chapeau|bandana|claquette|tongs?\b|"
    r"chausson|pantoufle|socks?\b|beanie|backpack|bags?\b|"
    # En inglés (Carhartt WIP, Nike): gorras, cinturones, carteras, bañadores…
    r"caps?\b|hats?\b|belts?\b|wallets?\b|keychains?|scarf|scarves|totes?\b|briefs\b|swim|underwear|gloves?\b)"
)

# Palabra del nombre -> tipo. Gana la que aparece antes en el nombre («POLO PUNTO» es un polo); si dos
# empiezan en el mismo sitio, la más larga («Shirt Jac» es una sobrecamisa, no una camisa; «Sweat Pant»,
# un chándal). En español, francés e inglés (Nike y Carhartt WIP nombran en inglés: «Hooded Jacket»).
_TYPE_WORDS = [
    (r"sobrecamisas?|surchemises?|overshirts?|shirt[- ]?jac(?:ket)?s?|shackets?", "sobrecamisa"),
    (r"camisetas?|t-?shirts?|tee-?shirts?|debardeurs?|tees?|tank[- ]?tops?|longsleeves?", "camiseta"),
    (r"camisas?|chemises?|shirts?", "camisa"),
    (r"polos?", "polo"),
    (r"sudaderas?|hoodies?|sweats?|sweat-?shirts?", "sudadera"),
    (r"jersey|jerseis|cardigans?|sueter|pulls?|pull-?overs?|maille|sweaters?|jumpers?", "jersey"),
    (r"abrigo|gabardina|trench|parkas?|anorak|plumifero|manteaux?|doudounes?|caban|coats?|overcoats?|"
     r"puffers?|down jackets?", "abrigo"),
    (r"cazadora|chaqueta|bombers?|blazers?|americana|chaleco|vestes?|blousons?|jackets?|vests?|"
     r"windbreakers?", "chaqueta"),
    (r"bermudas?|shorts?", "pantalón corto"),
    (r"jeans?|vaqueros?", "vaquero"),
    (r"joggers?|chandal|joggings?|survetements?|sweat ?pants?|track ?pants?|tracksuits?", "chándal"),
    (r"pantalon|pantalones|pantalons|pants?|trousers?", "pantalón"),
    (r"chinos?", "chino"),
    (r"zapatillas?|sneakers?|deportivas?|baskets?|trainers?", "zapatillas"),
    (r"botas?|botin|botines|bottes?|bottines?|boots?|chukkas?", "botas"),
    (r"zapatos?|mocasin|mocasines|nauticos?|sandalias?|alpargatas?|zuecos?|chaussures?|mocassins?|derbys?|"
     r"richelieus?|loafers?|sandales?|sabots?|espadrilles?", "zapatos"),
]
_TYPE_RE = [(re.compile(rf"\b(?:{words})\b"), garment_type) for words, garment_type in _TYPE_WORDS]


def estimate_type(name: str, default: str | None = None) -> str | None:
    """El tipo de prenda por las palabras del nombre; si no dice nada, el de la categoría de la tienda.

    None = no es algo que quepa en el armario (calcetines, gorras…) o no se sabe qué es.
    """
    text = norm(name)
    if _NOT_A_GARMENT.search(text):
        return None
    found = [(m.start(), -len(m.group()), garment_type) for rx, garment_type in _TYPE_RE if (m := rx.search(text))]
    garment_type = min(found)[2] if found else default
    if garment_type == "pantalón" or (garment_type == "vaquero" and not found):
        # «PANTALÓN CHINO», «PANTALÓN JOGGER», «PANTALÓN CORTO»: lo que manda es el apellido.
        if re.search(r"\b(cortos?|courts?|bermudas?|shorts?)\b", text):
            return "pantalón corto"
        if re.search(r"\bchinos?\b", text):
            return "chino"
        if re.search(r"\b(joggers?|joggings?|chandal|survetements?|sweat ?pants?|track ?pants?)\b", text):
            return "chándal"
        if re.search(r"\b(jeans?|vaqueros?|denim)\b", text):
            return "vaquero"
    return garment_type


# Texto de la tienda -> nuestra paleta. De lo más concreto a lo más general: «Rojo burgundy» es burdeos.
# En español, francés (Zara Francia, Courir, JD Sports) e inglés (los colores de las zapatillas).
_COLOR_WORDS = [
    (r"multicolor|varios|combinad|combine|estampad|\bmulti\b", "multicolor"),
    (r"azul hielo|bleu glace|ice blue", "celeste"),
    # «Bleu gris» (Bonobo) es un azul agrisado: sin esto ganaba «gris», que va antes en la lista.
    (r"bleu gris|blue gr[ae]y", "azul"),
    (r"vert gris|green gr[ae]y", "verde"),
    # «Glace» a secas (Pull&Bear, Bershka) es un blanco hielo tirando a beige muy claro, no un azul: un
    # pantalón «Glace» claramente beige claro salía como celeste (visto por el usuario, 18-11-2026).
    (r"blanco roto|blanco hueso|off white|off-white|crudo|ecru|hueso|marfil|nata|crema|tiza|mantequilla|"
     r"blanc casse|creme|cream|ivoire|ivory|coquille|\bsail\b|vanille|vanilla|\bglace\b|\bbone\b|\bsalt\b|"
     r"\bnatural\b|\bnaturel\b|\bcru\b|\bchalk\b|\blinen\b|\bphantom\b", "crudo"),
    (r"marino|navy|azul oscuro|azul noche|tinta|marine|bleu nuit|bleu fonce|midnight|obsidian", "azul marino"),
    (r"azul claro|azul cielo|azul palido|celeste|bleu clair|bleu ciel|bleu pale|light blue|sky blue|"
     r"baby blue|\bciel\b", "celeste"),
    (r"oliva|khaki|kaki|caqui|militar|musgo|olive|\bmousse\b", "verde oliva"),
    (r"burdeos|burgundy|granate|vino|berenjena|bordeaux|maroon|\bwine\b|aubergine|grenat", "burdeos"),
    (r"marron|chocolate|conac|tabaco|cuero|tostado|caramelo|camel|taupe|topo|moka|cafe|castano|avellana|cobre|"
     r"\bbrun|brown|chocolat|cognac|\btan\b|noisette|bronze|cuivre|\bmiel\b|wheat|tobacco|\bcuir\b|\bmocha\b|"
     r"espresso|coffee|cardboard", "marrón"),
    (r"beige|arena|piedra|vison|nude|\bsable\b|\bsand\b|stone|\bpierre\b|sesame|\bputty\b|oatmeal|\bdesert\b|"
     r"\bdune\b", "beige"),
    (r"gris|antracita|plomo|plata|marengo|ceniza|humo|grafito|carbon|grey|gray|argent|silver|anthracite|"
     r"charcoal|graphite|\bash\b|plomb|acier|ardoise|slate|platinum|platine|cement", "gris"),
    (r"negro|black|noir", "negro"),
    (r"blanco|white|blanc", "blanco"),
    (r"azul|indigo|anil|petroleo|petrole|denim|cobalto|turquesa|bleu|blue|turquoise|royal|\bteal\b|\bbrut\b",
     "azul"),
    (r"verde|verdos|botella|bouteille|menta|esmeralda|\bvert|green|\bmint|menthe|sapin|\bsage\b|\bfir\b|\bleaf\b|\bforest\b|"
     r"\bpine\b|\bmoss\b", "verde"),
    (r"rojo|rojiz|coral|rouge|\bred\b|corail", "rojo"),
    (r"amarillo|mostaza|vainilla|lima|ocre|jaune|yellow|moutarde|\bor\b|\bdore|gold|\bvolt\b", "amarillo"),
    (r"naranja|teja|terracota|ladrillo|oxido|calabaza|orange|rouille|brique", "naranja"),
    (r"rosa|fucsia|salmon|maquillaje|\brose\b|pink|fuchsia|saumon", "rosa"),
    (r"morado|lila|malva|violeta|lavanda|purpura|violet|purple|lilas|mauve|lavande|prune|\bplum\b|lilac|"
     r"lavender", "morado"),
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


# Palabras de color que no dicen un color claro por sí solas: tonos de nombre «poético» que cada tienda
# usa a su manera (hielo, tiza, piedra, arena, humo…). Si la tienda da además el tono (#rrggbb), manda el
# tono; si no, valen como pista.
_DOUBTFUL = {
    "glace", "ice", "tiza", "coquille", "sail", "vanille", "vanilla", "mantequilla", "nata", "crema", "creme",
    "cream", "hueso", "piedra", "pierre", "stone", "arena", "sable", "sand", "nude", "vison", "humo", "ceniza",
    "smoke", "tinta", "militar", "musgo", "tabaco", "cuero", "tostado", "caramelo", "miel", "wheat", "topo",
    "taupe", "plomo", "plata", "argent", "silver", "botella", "bouteille", "sapin", "maquillaje", "royal",
    "petroleo", "lima", "ocre", "or", "dore", "gold", "bronze", "cuivre", "cobre", "oxido", "rouille", "teja",
    "ladrillo", "brique", "calabaza", "prune", "berenjena", "aubergine", "vino", "wine", "moka", "cafe",
    "avellana", "noisette", "castano", "bone", "obsidian", "sage", "volt", "ash", "salt", "natural", "tobacco",
    "fir", "leaf", "forest", "pine", "moss", "mousse", "cuir", "petrole", "chalk", "linen", "phantom", "sesame",
    "putty", "oatmeal", "desert", "dune", "mocha", "espresso", "coffee", "cardboard", "platinum", "platine",
    "cement", "teal", "brut", "plum", "naturel",
}

# El color aún no se sabe: la tienda no lo dice en el listado (Courir) o lo dice con palabras que no
# conocemos y sin tono. No es «multicolor»: no suma ni resta en la nota hasta que llegue la ficha.
UNKNOWN_COLOR = ""


def estimate_color(store_color: str | None, hex_color: str | None = None) -> str:
    """Del texto de la tienda («Marino», «Khaki», «Gris vigoré») a nuestra paleta.

    Si el texto no dice nada conocido, el tono más cercano; sin tono, `UNKNOWN_COLOR` (""). Si solo lo
    dice una palabra dudosa (`_DOUBTFUL`: «Glace», «Tiza», «Piedra») y la tienda da el tono, manda el tono.
    """
    text = norm(store_color)
    # «Noir/Blanc», «marron/blanc», «Black/White»: el primero es el principal.
    for part in [*text.split("/"), text] if "/" in text else [text]:
        for rx, color in _COLOR_RE:
            match = rx.search(part)
            if match:
                if match.group().strip() in _DOUBTFUL and nearest_color(hex_color):
                    return nearest_color(hex_color)
                return color
    return nearest_color(hex_color) or UNKNOWN_COLOR


def estimate_pattern(name: str) -> str:
    text = norm(name)
    if re.search(r"\b(rayas?|listas?|rayures?|raye(e|s|es)?|stripes?)\b", text):
        return "rayas"
    if re.search(r"\b(cuadros?|vichy|tartan|carreaux|ecossais(e|es)?|checks?)\b", text):
        return "cuadros"
    if re.search(r"colou?r ?block|\bbloques?\b", text):
        return "bloques de color"
    if re.search(r"estampad|\bprint|grafic|graphique|ilustracion|\btext[oe]\b|slogan|dibujo|imprim|\bmotifs?\b", text):
        return "gráfico"
    if re.search(
        r"\b(textura|texturizad[oa]|estructura|pana|borreguito|trenzad[oa]|canale|texture(e|s|es)?|"
        r"structure(e|s|es)?|velours|cotele(e|s|es)?|cannele(e|s|es)?|tresse(e|s|es)?|gaufre(e|s|es)?)\b", text
    ):
        return "texturizado"
    return "liso"


def estimate_style(name: str, garment_type: str) -> str:
    text = norm(name)
    if garment_type == "chándal" or re.search(r"tecnic|techni|training|running|deportiv|athletic|\bsport", text):
        return "deportivo"
    if garment_type in ("camisa", "chino", "zapatos") or re.search(
        r"\b(traje|blazer|americana|vestir|sastre|oxford|costume|habille(e|s|es)?|tailleur)\b", text
    ):
        return "smart casual"
    return "casual"


def estimate_season(name: str, garment_type: str) -> str:
    """La misma regla por tipo de prenda que sigue la IA (services/ai/base.py)."""
    text = norm(name)
    if garment_type in ("sudadera", "jersey", "abrigo", "botas"):
        return "invierno"
    if garment_type == "pantalón corto" or re.search(
        r"\b(lino|tirantes|sin mangas|lin|sans manches|debardeur)\b", text
    ):
        return "verano"
    if garment_type == "chaqueta" and re.search(
        r"acolchad|plumifer|puffer|borreg|\blana\b|sherpa|grues|matelasse|rembourre|doudoune|\blaine\b|"
        r"mouton|fourre|polaire", text
    ):
        return "invierno"
    if garment_type == "camisa" and re.search(r"franela|flanelle", text):
        return "invierno"
    return "todo_el_ano"


# ---------- Calzado (Courir, JD Sports): el nombre es un modelo, no una descripción

_BOOT = re.compile(r"\b(botas?|botin(es)?|bottes?|bottines?|boots?|chukkas?)\b")
_SHOE = re.compile(r"\b(zapatos?|mocasin(es)?|mocassins?|loafers?|derbys?|richelieus?|chaussures? de ville)\b")


def estimate_shoe_type(name: str) -> str | None:
    """Zapatillas, salvo que el nombre diga claramente bota o zapato. None si no es calzado del armario
    (chanclas, calcetines…)."""
    text = norm(name)
    if _NOT_A_GARMENT.search(text):
        return None
    if _BOOT.search(text):
        return "botas"
    if _SHOE.search(text):
        return "zapatos"
    return "zapatillas"


# Siglas que se escriben en mayúsculas aunque el resto vaya en formato de título.
_UPPER = {"asics", "hoka", "ugg", "dc", "og", "sb", "gtx", "se", "lx", "qs", "sp", "prm", "nyc", "usa", "uk", "us",
          "ii", "iii", "iv", "gs", "nb", "xt", "fc", "ea7"}


def title_case(text: str) -> str:
    """«AIR JORDAN 3 RETRO TRUE BLUE» -> «Air Jordan 3 Retro True Blue»; «GEL-NYC» -> «Gel-NYC».
    Los nombres de zapatillas son modelos: en formato de frase quedaban raros («Air jordan 3…»)."""

    def word(part: str) -> str:
        if not part:
            return part
        if part.lower() in _UPPER or (any(ch.isdigit() for ch in part) and any(ch.isalpha() for ch in part)):
            return part.upper()
        return part[:1].upper() + part[1:].lower()

    return " ".join("-".join(word(p) for p in w.split("-")) for w in " ".join((text or "").split()).split(" "))


# Marcas de varias palabras (o con su forma propia). La clave es la «familia»: Adidas Originals es Adidas.
_BRAND_FAMILIES = {
    "new balance": "New Balance", "under armour": "Under Armour", "the north face": "The North Face",
    "le coq sportif": "Le Coq Sportif", "dr martens": "Dr. Martens", "dr. martens": "Dr. Martens",
    "on running": "On", "on": "On", "air jordan": "Jordan", "tommy hilfiger": "Tommy Hilfiger",
    "calvin klein": "Calvin Klein", "ralph lauren": "Ralph Lauren", "polo ralph lauren": "Ralph Lauren",
    "emporio armani": "Armani", "hugo boss": "Boss",
}


def brand_name(brand: str | None) -> str:
    """La marca como se enseña: «ADIDAS ORIGINALS» -> «Adidas Originals», «asics» -> «ASICS»."""
    brand = " ".join((brand or "").split())
    return title_case(brand)[:40] if brand else ""


def brand_family(brand: str | None) -> str:
    """La familia de la marca, para aprender los gustos: «Adidas Originals» y «adidas» son «Adidas»,
    «Nike Sportswear» es «Nike», «New Balance» sigue siendo «New Balance». "" si no hay marca."""
    text = " ".join(norm(brand).split())
    if not text:
        return ""
    for key in sorted(_BRAND_FAMILIES, key=len, reverse=True):
        if text == key or text.startswith(key + " "):
            return _BRAND_FAMILIES[key]
    return title_case(text.split(" ")[0])
