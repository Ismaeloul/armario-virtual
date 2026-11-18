"""Traducción al español de los textos de las tiendas que no están en español (Zara Francia, Courir,
JD Sports .fr): nombre, color y composición de lo que se enseña en Compras.

Solo texto, en lote: una llamada por cada ~40 textos. Primero Codex (la suscripción del usuario) y, si
no está o falla, Claude si hay API key. Si fallan los dos no pasa nada: se enseña el original y se
vuelve a intentar la próxima vez. La respuesta tiene que traer exactamente un texto por cada uno que
se pidió, en el mismo orden; si no cuadra, se descarta entera.

La puntuación nunca depende de esto: se hace siempre con el texto original de la tienda.
"""
import json
import logging
import time

from .base import AnalysisError
from .claude import ClaudeAnalyzer
from . import codex_models
from .codex import CodexAnalyzer

log = logging.getLogger("armario.traduccion")

BATCH = 40  # textos por llamada
MAX_TEXT = 300  # caracteres por texto (una composición larga se corta)

SCHEMA = {
    "type": "object",
    "properties": {"traducciones": {"type": "array", "items": {"type": "string"}}},
    "required": ["traducciones"],
    "additionalProperties": False,
}

PROMPT = """Traduce al español de España estos textos de una tienda de ropa francesa (nombres de prendas
y de zapatillas, nombres de colores y composiciones de tejido). Escribe como lo haría una tienda de
ropa española: natural, en formato de frase (solo la primera letra en mayúscula, salvo nombres propios).

Reglas:
- No traduzcas marcas ni nombres propios de modelos («Air Force 1», «Samba OG», «Gel-Kayano 14»,
  «574», «Cloudtilt»): se quedan tal cual, con sus mayúsculas.
- No inventes nada que no diga el original. Si un texto ya está en español o no tiene nada que
  traducir, devuélvelo igual.
- Ejemplos: «Sweat à capuche zippé» → «Sudadera con capucha y cremallera»; «Polo en maille
  structuré» → «Polo de punto texturizado»; «Bleu marine» → «Azul marino»; «Écru / Chiné» → «Crudo /
  Jaspeado»; «Tige : textile et synthétique» → «Parte superior: textil y sintético».
- Devuelve exactamente {n} traducciones, una por texto y en el mismo orden.

Textos (JSON):
{texts}
"""


def _parse(raw: str, expected: int) -> list[str] | None:
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    items = data.get("traducciones") if isinstance(data, dict) else None
    if not isinstance(items, list) or len(items) != expected or not all(isinstance(t, str) for t in items):
        return None
    out = [" ".join(t.split())[:MAX_TEXT] for t in items]
    return out if all(out) else None


def _codex(prompt: str) -> str:
    analyzer = CodexAnalyzer()
    if not analyzer.available():
        raise AnalysisError("Codex no está instalado")
    # Con el modelo y el esfuerzo de traducir (Ajustes), no los de analizar fotos.
    return analyzer.analyze([], prompt, schema=SCHEMA, timeout=120, purpose=codex_models.TRANSLATION)


def _claude(prompt: str) -> str:
    analyzer = ClaudeAnalyzer()
    if not analyzer.available():
        raise AnalysisError("Claude no está configurado")
    return analyzer.analyze([], prompt, schema=SCHEMA, timeout=60)


# Por orden: si el primero falla (o no cuadra), el siguiente. Los tests ponen aquí un traductor falso.
BACKENDS = [("codex", _codex), ("claude", _claude)]


def _batch(texts: list[str]) -> list[str] | None:
    prompt = PROMPT.format(n=len(texts), texts=json.dumps(texts, ensure_ascii=False, indent=0))
    for name, backend in BACKENDS:
        started = time.monotonic()
        try:
            raw = backend(prompt)
        except AnalysisError as exc:
            log.info("Traducción con %s no disponible: %s", name, exc)
            continue
        except Exception:
            log.exception("Traducción con %s: error inesperado", name)
            continue
        out = _parse(raw, len(texts))
        if out is not None:
            log.info("Traducidos %s textos con %s en %.1f s", len(texts), name, time.monotonic() - started)
            return out
        log.warning("Traducción con %s: la respuesta no cuadra con lo pedido; se descarta", name)
    return None


def translate(texts: list[str]) -> dict[str, str]:
    """Original -> traducción, de los que se han podido traducir. Repetidos y vacíos se piden una vez."""
    unique = list(dict.fromkeys(" ".join(t.split())[:MAX_TEXT] for t in texts if t and t.strip()))
    done: dict[str, str] = {}
    for start in range(0, len(unique), BATCH):
        chunk = unique[start : start + BATCH]
        out = _batch(chunk)
        if out is None:
            continue
        done.update(zip(chunk, out))
    return done
