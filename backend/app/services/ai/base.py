"""Interfaz común de los analizadores de prendas.

Cada proveedor recibe las mismas fotos, el mismo prompt y el mismo esquema, y devuelve
JSON en bruto. La validación contra las listas cerradas se hace aquí, igual para todos.
"""
import json
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from ... import catalog
from ...schemas import GarmentDraft


class AnalysisError(Exception):
    """El proveedor no pudo analizar la prenda (no disponible, tiempo agotado, respuesta inválida…)."""


class Analyzer(Protocol):
    name: str

    def available(self) -> bool:
        """¿Está configurado? (binario instalado, API key presente…)"""

    def analyze(self, images: list[Path], prompt: str) -> str:
        """Devuelve el JSON de la respuesta como texto. Lanza AnalysisError si falla."""


_COLOR_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "enum": catalog.COLORS},
        "hex": {"type": "string", "description": "Color real de la prenda en formato #rrggbb"},
    },
    "required": ["name", "hex"],
    "additionalProperties": False,
}

# Esquema estricto: todas las propiedades son obligatorias y no se admiten extra,
# que es lo que exigen las salidas estructuradas de ambos proveedores.
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Nombre corto y descriptivo, 2-4 palabras"},
        "type": {"type": "string", "enum": list(catalog.TYPES)},
        "color_primary": _COLOR_SCHEMA,
        "color_primary_alt": {
            "type": ["string", "null"],
            "enum": [*catalog.COLORS, None],
            "description": "El otro color candidato si dudas entre dos para el principal; si no dudas, null",
        },
        "colors_secondary": {"type": "array", "items": _COLOR_SCHEMA},
        "pattern": {"type": "string", "enum": catalog.PATTERNS},
        "style": {"type": "string", "enum": catalog.STYLES},
        "details": {"type": "string", "description": "Corte, cuello, cierres… una frase breve"},
        "season": {"type": "string", "enum": list(catalog.SEASONS)},
        "brand": {"type": ["string", "null"]},
        "size": {"type": ["string", "null"]},
        "notes": {"type": "string", "description": "Una frase sobre cómo combinarla o cuándo usarla"},
        "confidence": {"type": "number", "description": "Certeza global entre 0 y 1"},
    },
    "required": [
        "name", "type", "color_primary", "color_primary_alt", "colors_secondary", "pattern", "style",
        "details", "season", "brand", "size", "notes", "confidence",
    ],
    "additionalProperties": False,
}

_PROMPT = """\
Eres el catalogador de un armario personal. Te paso {fotos} de {que}:
{orden}

Describe la prenda rellenando el esquema JSON. Reglas:
- Escribe en español.
- "name": nombre corto y natural, como lo diría su dueño ("Bomber negra", "Camiseta boxy cruda"). \
Siempre en singular, también los pantalones: "Vaquero ancho azul", no "Vaqueros anchos azules".
- "type", "pattern", "style", "season" y los nombres de color solo pueden ser valores de las listas del esquema. \
Elige el más cercano.
- "pattern": mira el dibujo de la tela, no su tacto.
  - "liso": un solo color, sin nada estampado.
  - "logo": un logo, una marca o un texto pequeño estampado o bordado como adorno (en el pecho, en la manga), \
aunque el resto sea de un color. La etiqueta cosida, el parche de la cintura de un vaquero o el logo de la \
suela no cuentan: eso lo lleva cualquier prenda.
  - "gráfico": un dibujo, una ilustración o un texto grande que ocupa buena parte de la prenda. \
Si delante hay un logo pequeño y detrás un dibujo grande, es "gráfico".
  - "bloques de color": varias franjas o paneles grandes de colores distintos.
  - "rayas" y "cuadros": solo si el patrón se repite por toda la tela.
  - "texturizado": solo cuando el relieve del tejido es lo que más se ve (punto grueso, pana, borreguito). \
El lavado desgastado de un vaquero no cuenta: un vaquero sin dibujo es "liso".
- "season": una sola, y decide por el tipo de prenda para que dos prendas parecidas salgan siempre igual.
  - "invierno": sudadera, jersey, abrigo, botas y chaquetas gruesas o acolchadas.
  - "verano": pantalón corto y prendas de tejido muy fino o fresco (lino, tirantes).
  - "todo_el_ano": camiseta, camisa, polo, vaquero, chino, pantalón, chándal, zapatillas, zapatos, \
sobrecamisa y chaquetas finas.
  - Solo te sales de esta regla si el tejido lo deja claro: una sudadera muy fina es "todo_el_ano", \
una camisa de franela gruesa es "invierno".
- "color_primary": el color dominante. "colors_secondary": otros colores visibles (lista vacía si es de un solo color). \
En "hex" pon el tono real que ves en la foto.
- "color_primary_alt": si el color principal está entre dos nombres de la lista y otra persona podría elegir el otro (blanco o crudo, gris o negro, azul o celeste, beige o marrón, verde o verde oliva…), pon aquí ese segundo candidato. Si el color es claro, null. No lo uses para los colores secundarios.
- {marca}
- "confidence": tu certeza global entre 0 y 1. Bájala si la foto es mala o la prenda es ambigua.

Responde únicamente con el JSON. No ejecutes comandos ni leas otros archivos."""

_SIN_ETIQUETA = (
    '"brand" y "size": solo si se leen con claridad en una etiqueta o logo de las fotos. Si no, null. No adivines.'
)
_CON_ETIQUETA = (
    '"brand" y "size": léelos de la foto de la etiqueta. "brand" es la marca tal como está escrita. '
    '"size" es la talla tal como aparece (S, M, L, XL, 42, 43 EU…); si hay varias, la europea o la internacional. '
    "Si alguno no se lee con claridad, null. No adivines. La etiqueta no cuenta para los colores ni el estampado."
)


_VISTAS = {
    # tipo de artículo -> (qué es, foto principal, segunda, tercera)
    "ropa": ("UNA prenda de ropa de hombre", "la parte delantera", "la parte trasera", "otro ángulo de la prenda"),
    "calzado": (
        "UN par de zapatillas o zapatos de hombre",
        "el lateral",
        "la vista de frente o desde arriba",
        "el otro lateral",
    ),
}


def build_prompt(has_back: bool, has_label: bool, has_extra: bool = False, kind: str = "ropa") -> str:
    """Las instrucciones dependen de qué se fotografía, qué fotos se mandan y en qué orden."""
    what, first, second, third = _VISTAS.get(kind, _VISTAS["ropa"])
    order = [f"- Foto 1: {first}."]
    if has_back:
        order.append(f"- Foto {len(order) + 1}: {second}.")
    if has_extra:
        order.append(f"- Foto {len(order) + 1}: {third}.")
    if has_label:
        order.append(f"- Foto {len(order) + 1}: la etiqueta, en primer plano.")
    if kind == "calzado":
        order.append('Es calzado: "type" solo puede ser "zapatillas", "zapatos" o "botas".')
    count = len([line for line in order if line.startswith("- Foto")])
    return _PROMPT.format(
        fotos="una foto" if count == 1 else f"{count} fotos",
        que=what,
        orden="\n".join(order),
        marca=_CON_ETIQUETA if has_label else _SIN_ETIQUETA,
    )


def parse_draft(raw: str) -> GarmentDraft:
    """Valida la respuesta de un proveedor. Una lista cerrada incumplida cuenta como fallo."""
    text = raw.strip()
    if text.startswith("```"):  # por si el modelo envuelve el JSON en un bloque de código
        text = text.strip("`")
        text = text[text.find("{"):]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AnalysisError("La IA no devolvió un JSON válido") from exc
    try:
        return GarmentDraft.model_validate(data)
    except ValidationError as exc:
        campos = ", ".join(sorted({str(e["loc"][0]) for e in exc.errors()}))
        raise AnalysisError(f"La respuesta de la IA no cumple el esquema ({campos})") from exc
