"""Claude por la API de Anthropic (API key en ANTHROPIC_API_KEY)."""
import base64
import os
from pathlib import Path

import anthropic

from ... import config
from .base import OUTPUT_SCHEMA, PROMPT, AnalysisError


class ClaudeAnalyzer:
    name = "claude"

    def available(self) -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    def analyze(self, images: list[Path]) -> str:
        if not self.available():
            raise AnalysisError("Claude no está configurado (falta ANTHROPIC_API_KEY)")

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
        content.append({"type": "text", "text": PROMPT})

        client = anthropic.Anthropic(timeout=config.AI_TIMEOUT_SECONDS, max_retries=1)
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
