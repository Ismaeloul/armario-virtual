"""Claude por la API de Anthropic (API key pegada en Ajustes o en ANTHROPIC_API_KEY)."""
import base64
import os
from pathlib import Path

import anthropic

from ... import config
from ...db import SessionLocal
from ...models import Setting
from .base import OUTPUT_SCHEMA, AnalysisError

API_KEY_SETTING = "anthropic_api_key"


def api_key() -> str | None:
    """La API key: la de Ajustes (pegada en la app) o, si no hay, la del entorno."""
    with SessionLocal() as db:
        stored = db.get(Setting, API_KEY_SETTING)
    if stored and stored.value:
        return stored.value
    return os.environ.get("ANTHROPIC_API_KEY") or None


class ClaudeAnalyzer:
    name = "claude"

    def available(self) -> bool:
        return api_key() is not None

    def analyze(self, images: list[Path], prompt: str) -> str:
        key = api_key()
        if not key:
            raise AnalysisError("Claude no está configurado (falta la API key)")

        content: list[dict] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/webp",
                    "data": base64.standard_b64encode(path.read_bytes()).decode("utf-8"),
                },
            }
            for path in images
        ]
        content.append({"type": "text", "text": prompt})

        client = anthropic.Anthropic(api_key=key, timeout=config.AI_TIMEOUT_SECONDS, max_retries=1)
        try:
            response = client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=4000,
                output_config={
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
                },
                messages=[{"role": "user", "content": content}],
            )
        except anthropic.AuthenticationError as exc:
            raise AnalysisError("La API key de Claude no es válida") from exc
        except anthropic.RateLimitError as exc:
            raise AnalysisError("Claude ha alcanzado el límite de peticiones") from exc
        except anthropic.APIStatusError as exc:
            raise AnalysisError(f"Claude devolvió un error ({exc.status_code})") from exc
        except anthropic.APIConnectionError as exc:
            raise AnalysisError("No se pudo conectar con Claude") from exc

        if response.stop_reason == "refusal":
            raise AnalysisError("Claude ha rechazado analizar la imagen")
        if response.stop_reason == "max_tokens":
            raise AnalysisError("La respuesta de Claude se cortó")

        text = next((b.text for b in response.content if b.type == "text"), None)
        if not text:
            raise AnalysisError("Claude no devolvió contenido")
        return text
