"""Listas cerradas del armario. Las usa el backend para validar, la IA como enumerados
y el frontend (vía GET /api/catalog) para pintar los selectores."""

CATEGORIES = {
    "parte_superior": "Parte superior",
    "capa_exterior": "Capa exterior",
    "parte_inferior": "Parte inferior",
    "calzado": "Calzado",
}

# tipo -> categoría (el outfit de la Fase 2 se monta por categorías)
TYPES = {
    "camiseta": "parte_superior",
    "camisa": "parte_superior",
    "polo": "parte_superior",
    "sudadera": "parte_superior",
    "jersey": "parte_superior",
    "sobrecamisa": "capa_exterior",
    "chaqueta": "capa_exterior",
    "abrigo": "capa_exterior",
    "pantalón": "parte_inferior",
    "vaquero": "parte_inferior",
    "chino": "parte_inferior",
    "pantalón corto": "parte_inferior",
    "chándal": "parte_inferior",
    "zapatillas": "calzado",
    "zapatos": "calzado",
    "botas": "calzado",
}

SEASONS = {
    "verano": "Verano",
    "invierno": "Invierno",
    "todo_el_ano": "Todo el año",
}

COLORS = [
    "negro", "blanco", "gris", "beige", "crudo", "marrón", "azul marino", "azul", "celeste",
    "verde", "verde oliva", "rojo", "burdeos", "amarillo", "naranja", "rosa", "morado", "multicolor",
]

# Tono por defecto de cada color, para cuando no hay foto analizada de la que sacarlo
# (los mismos que frontend/src/lib/colors.ts).
COLOR_HEX = {
    "negro": "#1b1b1e", "blanco": "#ffffff", "gris": "#8e918d", "beige": "#d6cbbe", "crudo": "#f1ede6",
    "marrón": "#6b4a34", "azul marino": "#1f2a44", "azul": "#2f5fa8", "celeste": "#a9c7e8",
    "verde": "#3f7d4f", "verde oliva": "#6b6b3a", "rojo": "#b3261e", "burdeos": "#6d1f2c",
    "amarillo": "#e6c229", "naranja": "#e07b2a", "rosa": "#e7a6b8", "morado": "#6b4fa0",
    "multicolor": "#9aa0a6",
}

PATTERNS = ["liso", "rayas", "cuadros", "bloques de color", "gráfico", "logo", "texturizado"]

STYLES = ["casual", "smart casual", "deportivo", "formal"]

# Palabras clave de la prenda: las reglas de estilo las usan tal cual, sin leer el texto de detalles.
# No se aplican al calzado (se quedan vacías).
CLOSURES = ["sin cierre", "botones", "media cremallera", "cremallera"]
FITS = ["ajustado", "normal", "ancho"]
THICKNESSES = ["fino", "medio", "grueso"]

AI_PROVIDERS = ["codex", "claude"]
THEMES = ["claro", "oscuro", "sistema"]


def category_of(garment_type: str) -> str:
    return TYPES[garment_type]


def as_dict() -> dict:
    return {
        "categories": CATEGORIES,
        "types": TYPES,
        "seasons": SEASONS,
        "colors": COLORS,
        "patterns": PATTERNS,
        "styles": STYLES,
        "closures": CLOSURES,
        "fits": FITS,
        "thicknesses": THICKNESSES,
        "ai_providers": AI_PROVIDERS,
        "themes": THEMES,
    }
