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

PATTERNS = ["liso", "rayas", "cuadros", "gráfico", "logo", "texturizado"]

STYLES = ["casual", "smart casual", "deportivo", "formal"]

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
        "ai_providers": AI_PROVIDERS,
        "themes": THEMES,
    }
