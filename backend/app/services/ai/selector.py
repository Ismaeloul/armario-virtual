"""Elige proveedor: primero el de Ajustes; si falla, el otro. Nunca en silencio:
el resultado dice quién analizó y si hubo que recurrir al plan B."""
import logging
from dataclasses import dataclass
from pathlib import Path

from ...schemas import GarmentDraft
from .base import AnalysisError, Analyzer, parse_draft
from .claude import ClaudeAnalyzer
from .codex import CodexAnalyzer

log = logging.getLogger("armario.ai")

ANALYZERS: dict[str, Analyzer] = {
    "codex": CodexAnalyzer(),
    "claude": ClaudeAnalyzer(),
}


@dataclass
class AnalysisResult:
    draft: GarmentDraft | None
    provider: str | None
    fallback_used: bool
    error: str | None


def analyze(images: list[Path], preferred: str) -> AnalysisResult:
    order = [preferred] + [name for name in ANALYZERS if name != preferred]
    errors: list[str] = []

    for name in order:
        analyzer = ANALYZERS[name]
        if not analyzer.available():
            errors.append(f"{name}: no configurado")
            continue
        try:
            draft = parse_draft(analyzer.analyze(images))
        except AnalysisError as exc:
            log.warning("Análisis con %s fallido: %s", name, exc)
            errors.append(f"{name}: {exc}")
            continue
        return AnalysisResult(draft=draft, provider=name, fallback_used=name != preferred, error=None)

    return AnalysisResult(draft=None, provider=None, fallback_used=False, error="; ".join(errors))
