import io
import os
import sys
import tempfile
from pathlib import Path

# El entorno se fija antes de importar la app: la base de datos y las fotos van a una carpeta temporal.
_TMP = tempfile.mkdtemp(prefix="armario-tests-")
os.environ["ARMARIO_DATA_DIR"] = _TMP
os.environ["ARMARIO_FRONTEND_DIST"] = str(Path(_TMP) / "sin-frontend")
os.environ["ARMARIO_SHOP_AUTO"] = "0"  # sin bucle de tandas: los tests nunca llaman a las tiendas
os.environ["ARMARIO_SHOP_TRANSLATE"] = "0"  # ni a Codex para traducir
os.environ["ARMARIO_SHOP_NIGHT_PAUSE"] = "0"  # el recorrido del catálogo, sin pausas
os.environ["ARMARIO_SHOP_DAY_PAUSE"] = "0"
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.ai import selector  # noqa: E402
from app.services.ai import translate  # noqa: E402
from app.services.shops.fetch import Fetcher  # noqa: E402
from app.services.shops.zara import ZaraConnector  # noqa: E402

VALID_DRAFT = {
    "name": "Bomber negra",
    "type": "chaqueta",
    "color_primary": {"name": "negro", "hex": "#111111"},
    "colors_secondary": [],
    "pattern": "liso",
    "style": "casual",
    "details": "Cuello y puños elásticos, cremallera",
    "season": "invierno",
    "brand": None,
    "size": None,
    "notes": "Combina con casi todo",
    "confidence": 0.9,
}


class FakeAnalyzer:
    def __init__(self, name, response=None, error=None, is_available=True):
        self.name = name
        self.response = response
        self.error = error
        self.is_available = is_available
        self.calls = 0

    def available(self):
        return self.is_available

    def analyze(self, images, prompt):
        self.calls += 1
        self.images = list(images)
        self.prompt = prompt
        if self.error:
            raise self.error
        return self.response


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    """Ningún test sale a internet: si algo intenta pedirle una página a Zara, falla."""

    def _blocked(self, url, *args, **kwargs):
        raise AssertionError(f"Un test ha intentado llamar a la tienda: {url}")

    monkeypatch.setattr(ZaraConnector, "_get", _blocked)
    monkeypatch.setattr(Fetcher, "get", _blocked)  # Courir y JD Sports

    def _no_ai(prompt):
        raise AssertionError("Un test ha intentado traducir con la IA de verdad")

    monkeypatch.setattr(translate, "BACKENDS", [("codex", _no_ai)])


@pytest.fixture
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def analyzers(monkeypatch):
    """Sustituye los proveedores reales por dobles controlables."""

    def install(codex: FakeAnalyzer, claude: FakeAnalyzer):
        monkeypatch.setattr(selector, "ANALYZERS", {"codex": codex, "claude": claude})
        return codex, claude

    return install


@pytest.fixture
def photo_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (2400, 1800), (200, 180, 150)).save(buf, "JPEG")
    return buf.getvalue()
