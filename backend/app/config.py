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


def _pause(name: str, default: str) -> tuple[float, float]:
    """«6-10» -> (6.0, 10.0); «3» -> (3.0, 3.0). Segundos entre una página del listado y la siguiente."""
    for raw in (os.environ.get(name, default), default):
        low, _, high = raw.replace(",", ".").partition("-")
        try:
            low_f = float(low)
            high_f = float(high) if high else low_f
        except ValueError:
            continue
        return (max(0.0, min(low_f, high_f)), max(0.0, low_f, high_f))
    return (6.0, 10.0)


# El catálogo entero de cada tienda se lee de noche y despacio: pausas largas, con algo de variación.
# «Consultar ahora» (de día, con el usuario esperando) hace el mismo recorrido con pausas algo menores.
SHOP_NIGHT_PAUSE = _pause("ARMARIO_SHOP_NIGHT_PAUSE", "6-10")
SHOP_DAY_PAUSE = _pause("ARMARIO_SHOP_DAY_PAUSE", "3-5")
# Si una tienda bloqueó a mitad, al retomar se va aún más despacio.
SHOP_SLOW_FACTOR = float(os.environ.get("ARMARIO_SHOP_SLOW_FACTOR", "1.5"))
# Topes de seguridad por sección (que un fallo no deje el recorrido dando vueltas), no de catálogo.
# Se pueden cambiar por tienda: ARMARIO_SHOP_MAX_PAGES_ZARA, ARMARIO_SHOP_MAX_PRODUCTS_COURIR…
SHOP_MAX_PAGES = int(os.environ.get("ARMARIO_SHOP_MAX_PAGES", "60"))
# El reparto de la noche: cuántas tiendas se consultan como mucho en una misma noche, y cuántas de ellas
# «pesadas» (las de navegador con muchas secciones: Inditex, Jules, Bonobo). Las que no caben pasan a la
# noche siguiente. Con tres y dos, las veinte tiendas previstas caben una vez por semana (ver shops/__init__.py).
SHOP_STORES_PER_NIGHT = max(1, int(os.environ.get("ARMARIO_SHOP_STORES_PER_NIGHT", "3")))
SHOP_HEAVY_PER_NIGHT = max(1, int(os.environ.get("ARMARIO_SHOP_HEAVY_PER_NIGHT", "2")))
SHOP_MAX_PRODUCTS = int(os.environ.get("ARMARIO_SHOP_MAX_PRODUCTS", "3000"))
# La reserva: propuestas con ficha y fotos ya bajadas por delante de lo que el usuario lleva visto.
# Cuando quedan menos de SHOP_RESERVE_LOW por ver, se repone en segundo plano hasta SHOP_RESERVE.
SHOP_RESERVE = int(os.environ.get("ARMARIO_SHOP_RESERVE", "25"))
SHOP_RESERVE_LOW = int(os.environ.get("ARMARIO_SHOP_RESERVE_LOW", "15"))
# Colores que se dejan preparados (ficha y fotos) por propuesta en las tiendas que no pueden traer un
# color al momento (JD Sports), contando el que se ve.
SHOP_COLOR_PREP = int(os.environ.get("ARMARIO_SHOP_COLOR_PREP", "4"))


# Tiendas cuyo catálogo es demasiado grande para leerlo entero cada semana: por defecto solo las primeras
# páginas de cada sección (ordenadas por novedad). H&M: unos 5.100 artículos de hombre en ~145 páginas de 36;
# con ocho por sección se leen las novedades (~290 por sección). Se cambia con ARMARIO_SHOP_MAX_PAGES_HM.
SHOP_STORE_PAGES = {"hm": 8}


def shop_limit(store: str, kind: str) -> int:
    """Tope de seguridad de una tienda: «PAGES» (páginas por sección) o «PRODUCTS» (productos por sección)."""
    default = SHOP_MAX_PAGES if kind == "PAGES" else SHOP_MAX_PRODUCTS
    if kind == "PAGES":
        default = SHOP_STORE_PAGES.get(store, default)
    try:
        return max(1, int(os.environ.get(f"ARMARIO_SHOP_MAX_{kind}_{store.upper()}", default)))
    except ValueError:
        return default

PHOTO_MAX_SIDE = 1600
THUMB_MAX_SIDE = 480


def ensure_dirs() -> None:
    for d in (DATA_DIR, PHOTOS_DIR, ORIGINALS_DIR):
        d.mkdir(parents=True, exist_ok=True)
