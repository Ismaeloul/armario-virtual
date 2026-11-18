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
# Aislamiento que aplica Codex a sus propios comandos. "read-only" es lo seguro; dentro de un
# contenedor que no lo soporte se puede relajar, porque el contenedor ya aísla.
CODEX_SANDBOX = os.environ.get("CODEX_SANDBOX", "read-only")

# Claude: API de Anthropic con API key.
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-5-5")

# --- Compras (Fase 4) ---
# El bucle que cada hora mira si toca traer novedades de las tiendas. "0" lo apaga (tests, desarrollo).
SHOP_AUTO = os.environ.get("ARMARIO_SHOP_AUTO", "1") != "0"
SHOP_BATCH_SIZE = int(os.environ.get("ARMARIO_SHOP_BATCH", "40"))  # propuestas por tanda
SHOP_MORE_SIZE = int(os.environ.get("ARMARIO_SHOP_MORE", "20"))  # propuestas por cada «Ver más»
SHOP_PAUSE_SECONDS = float(os.environ.get("ARMARIO_SHOP_PAUSE", "1.0"))  # entre peticiones a la tienda
SHOP_TIMEOUT_SECONDS = float(os.environ.get("ARMARIO_SHOP_TIMEOUT", "20"))
# Traducir al español lo que llega de las tiendas en otro idioma (con Codex, o Claude si no).
SHOP_TRANSLATE = os.environ.get("ARMARIO_SHOP_TRANSLATE", "1") != "0"
SHOP_PAGES = int(os.environ.get("ARMARIO_SHOP_PAGES", "3"))  # páginas de 20 productos por categoría

PHOTO_MAX_SIDE = 1600
THUMB_MAX_SIDE = 480


def ensure_dirs() -> None:
    for d in (DATA_DIR, PHOTOS_DIR, ORIGINALS_DIR):
        d.mkdir(parents=True, exist_ok=True)
