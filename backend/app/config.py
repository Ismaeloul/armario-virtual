"""Configuración por variables de entorno. Todo lo persistente vive en DATA_DIR."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = Path(os.environ.get("ARMARIO_DATA_DIR", ROOT / "data")).resolve()
PHOTOS_DIR = DATA_DIR / "photos"
ORIGINALS_DIR = DATA_DIR / "originals"
DB_PATH = DATA_DIR / "armario.db"

# Build del frontend que sirve FastAPI en producción (un solo contenedor).
FRONTEND_DIST = Path(os.environ.get("ARMARIO_FRONTEND_DIST", ROOT / "frontend" / "dist"))

# Orígenes extra permitidos (p. ej. la app de Capacitor). Separados por comas.
CORS_ORIGINS = [o.strip() for o in os.environ.get("ARMARIO_CORS_ORIGINS", "").split(",") if o.strip()]

# --- IA ---
AI_TIMEOUT_SECONDS = int(os.environ.get("ARMARIO_AI_TIMEOUT", "90"))

# Codex: suscripción de ChatGPT a través del CLI (sin API key).
CODEX_BIN = os.environ.get("CODEX_BIN", "codex")
CODEX_MODEL = os.environ.get("CODEX_MODEL", "")  # vacío = el que use el CLI por defecto

# Claude: API de Anthropic con API key.
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-5-5")

PHOTO_MAX_SIDE = 1600
THUMB_MAX_SIDE = 480


def ensure_dirs() -> None:
    for d in (DATA_DIR, PHOTOS_DIR, ORIGINALS_DIR):
        d.mkdir(parents=True, exist_ok=True)
