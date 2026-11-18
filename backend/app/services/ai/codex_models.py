"""Qué modelo y qué esfuerzo de razonamiento usa Codex al analizar una prenda.

La lista de modelos no va escrita aquí: se lee de la caché que el propio CLI guarda en su carpeta
(`models_cache.json`), que es la lista de lo que la cuenta del usuario puede usar. Así no se queda vieja.
El modelo y el esfuerzo elegidos se guardan en Ajustes; vacío significa «lo que Codex traiga por defecto».
"""
import json
import os
from pathlib import Path

from ... import config

EFFORTS = ("low", "medium", "high")  # los que se ofrecen; los superiores tardan y gastan demasiado
MODEL_SETTING, EFFORT_SETTING = "codex_model", "codex_effort"


def _cache_file() -> Path:
    home = os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")
    return Path(home) / "models_cache.json"


def available() -> list[dict]:
    """Modelos con visión que el CLI ofrece a esta cuenta, en su orden. Vacío si aún no hay caché."""
    try:
        raw = json.loads(_cache_file().read_text(encoding="utf-8"))
        models = raw.get("models", [])
    except (OSError, ValueError, AttributeError):
        return []
    found = []
    for m in sorted((m for m in models if isinstance(m, dict)), key=lambda m: m.get("priority", 999)):
        if m.get("visibility") != "list" or "image" not in (m.get("input_modalities") or []):
            continue
        slug = m.get("slug")
        if not isinstance(slug, str) or not slug:
            continue
        levels = [lv.get("effort") for lv in m.get("supported_reasoning_levels") or [] if isinstance(lv, dict)]
        found.append({
            "slug": slug,
            "name": m.get("display_name") or slug,
            "efforts": [e for e in EFFORTS if e in levels],
            "default_effort": m.get("default_reasoning_level"),
        })
    return found


def chosen() -> tuple[str, str]:
    """(modelo, esfuerzo) guardados en Ajustes; cadena vacía = el de Codex por defecto."""
    from ...db import SessionLocal
    from ...models import Setting

    with SessionLocal() as db:
        values = {s.key: s.value for s in db.query(Setting).filter(Setting.key.in_((MODEL_SETTING, EFFORT_SETTING)))}
    model = values.get(MODEL_SETTING) or config.CODEX_MODEL
    effort = values.get(EFFORT_SETTING) or ""
    return model, effort if effort in EFFORTS else ""


def cli_args() -> list[str]:
    """Los argumentos de `codex exec` que fijan el modelo y el esfuerzo elegidos."""
    model, effort = chosen()
    args = []
    if model:
        args += ["--model", model]
    if effort:
        args += ["-c", f'model_reasoning_effort="{effort}"']
    return args
