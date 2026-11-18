"""Qué modelo y qué esfuerzo de razonamiento usa Codex: uno para analizar las fotos de las prendas y
otro, aparte, para traducir los nombres de las tiendas (puede ser uno pequeño y sin visión).

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
TRANSLATE_MODEL_SETTING, TRANSLATE_EFFORT_SETTING = "codex_translate_model", "codex_translate_effort"
TRANSLATE_DEFAULT_EFFORT = "low"  # traducir nombres no necesita pensar mucho
ANALYSIS, TRANSLATION = "analisis", "traduccion"  # para qué es la llamada


def _cache_file() -> Path:
    home = os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")
    return Path(home) / "models_cache.json"


def available(vision: bool = True) -> list[dict]:
    """Modelos que el CLI ofrece a esta cuenta, en su orden. Vacío si aún no hay caché. Con `vision`,
    solo los que leen imágenes (para analizar fotos); sin él, todos (para traducir vale cualquiera)."""
    try:
        raw = json.loads(_cache_file().read_text(encoding="utf-8"))
        models = raw.get("models", [])
    except (OSError, ValueError, AttributeError):
        return []
    found = []
    for m in sorted((m for m in models if isinstance(m, dict)), key=lambda m: m.get("priority", 999)):
        sees = "image" in (m.get("input_modalities") or [])
        if m.get("visibility") != "list" or (vision and not sees):
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
            "vision": sees,
        })
    return found


def chosen(purpose: str = ANALYSIS) -> tuple[str, str]:
    """(modelo, esfuerzo) guardados en Ajustes para analizar fotos o para traducir; cadena vacía = el de
    Codex por defecto (o el esfuerzo del modelo). Cada pareja va por su lado."""
    from ...db import SessionLocal
    from ...models import Setting

    translating = purpose == TRANSLATION
    keys = (TRANSLATE_MODEL_SETTING, TRANSLATE_EFFORT_SETTING) if translating else (MODEL_SETTING, EFFORT_SETTING)
    with SessionLocal() as db:
        values = {s.key: s.value for s in db.query(Setting).filter(Setting.key.in_(keys))}
    if translating:
        model = values.get(keys[0]) or ""
        effort = values[keys[1]] if keys[1] in values else TRANSLATE_DEFAULT_EFFORT
    else:
        model = values.get(keys[0]) or config.CODEX_MODEL
        effort = values.get(keys[1]) or ""
    return model, effort if effort in EFFORTS else ""


def cli_args(purpose: str = ANALYSIS) -> list[str]:
    """Los argumentos de `codex exec` que fijan el modelo y el esfuerzo elegidos para esa llamada."""
    model, effort = chosen(purpose)
    args = []
    if model:
        args += ["--model", model]
    if effort:
        args += ["-c", f'model_reasoning_effort="{effort}"']
    return args
