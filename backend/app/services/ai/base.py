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

    def analyze(self, images: list[Path]) -> str:
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
        "name", "type", "color_primary", "colors_secondary", "pattern", "style",
        "details", "season", "brand", "size", "notes", "confidence",
    ],
    "additionalProperties": False,
}

PROMPT = """\
Eres el catalogador de un armario personal. Te paso una o dos fotos de UNA prenda de ropa \
o calzado de hombre: la primera es la parte delantera y, si hay segunda, es la trasera.

Describe la prenda rellenando el esquema JSON. Reglas:
- Escribe en español.
- "name": nombre corto y natural, como lo diría su dueño ("Bomber negra", "Camiseta boxy cruda").
- "type", "pattern", "style", "season" y los nombres de color solo pueden ser valores de las listas del esquema. \
Elige el más cercano.
- "season": una sola. "verano" para prendas claramente de calor, "invierno" para prendas claramente de frío, \
"todo_el_ano" para el resto.
- "color_primary": el color dominante. "colors_secondary": otros colores visibles (lista vacía si es de un solo color). \
En "hex" pon el tono real que ves en la foto.
- "brand" y "size": solo si se leen con claridad en una etiqueta o logo de las fotos. Si no, null. No adivines.
- "confidence": tu certeza global entre 0 y 1. Bájala si la foto es mala o la prenda es ambigua.

Responde únicamente con el JSON. No ejecutes comandos ni leas otros archivos."""


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
