"""Peticiones educadas a una tienda: una cada vez, con pausa, con tiempo máximo y sin insistir.

Lo usan Courir (páginas y fotos) y las fotos de las tiendas de navegador (JD Sports, Pull&Bear y
Bershka, de sus CDN). Zara tiene el suyo (es anterior y responde JSON).

- Una petición cada vez (cerrojo) y una pausa mínima entre ellas.
- Sin cookies: cada petición sale limpia. Courir respondía 403 a la segunda petición si se le
  devolvían las cookies de la primera; sin ellas, 200.
- Si la tienda bloquea (un 429, una página de comprobación o dos 403 seguidos), el conector se da
  por bloqueado un rato: las siguientes peticiones fallan al momento con el mismo mensaje, sin
  tocar la tienda. Así un bloqueo se apunta como fallo de la tienda (panel «Tiendas») y no se insiste.
"""
import threading
import time
from dataclasses import dataclass

import httpx

from .base import ShopError

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
HTML = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
# Sin AVIF: las fotos se guardan con Pillow, y no todas sus versiones lo leen.
IMAGE = "image/webp,image/jpeg,image/png,image/*;q=0.8,*/*;q=0.5"
BLOCK_SECONDS = 30 * 60  # lo que se deja en paz a una tienda que ha bloqueado
_CHALLENGE = ("cf-chl", "challenge-platform", "just a moment", "captcha", "datadome", "px-captcha")


@dataclass
class Page:
    status: int
    content: bytes

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")


class Fetcher:
    def __init__(self, store: str, pause: float, timeout: float, accept_language: str):
        self.store = store
        self.pause = pause
        self.timeout = timeout
        self.accept_language = accept_language
        self.requests = 0
        self._lock = threading.Lock()
        self._last = 0.0
        self._client: httpx.Client | None = None
        self._blocked_until = 0.0
        self._blocked_why = ""
        self._forbidden = 0  # 403 seguidos

    # --- lo que usan los conectores

    def get(self, url: str, accept: str = HTML, pause: float | None = None) -> Page:
        """La página (o la foto). Lanza ShopError si no se pudo pedir o si la tienda bloquea; un 404 o un
        410 se devuelven tal cual (el producto ya no existe: no es un fallo)."""
        with self._lock:
            if time.monotonic() < self._blocked_until:
                raise ShopError(self._blocked_why)
            wait = self._last + (self.pause if pause is None else pause) - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            headers = {"User-Agent": USER_AGENT, "Accept": accept, "Accept-Language": self.accept_language}
            try:
                self.requests += 1
                page = self._httpx(url, headers)
            finally:
                self._last = time.monotonic()
            self._check(page)
            return page

    # --- por dentro

    def _httpx(self, url: str, headers: dict) -> Page:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout, follow_redirects=True)
        self._client.cookies.clear()  # sin cookies: ver arriba
        try:
            response = self._client.get(url, headers=headers)
        except httpx.TimeoutException as exc:
            raise ShopError(f"tiempo agotado ({self.timeout:g} s)") from exc
        except httpx.HTTPError as exc:
            raise ShopError(f"no se pudo conectar ({type(exc).__name__})") from exc
        finally:
            self._client.cookies.clear()
        return Page(response.status_code, response.content)

    def _block(self, why: str) -> None:
        self._blocked_until = time.monotonic() + BLOCK_SECONDS
        self._blocked_why = f"{why}: no se insiste hasta dentro de un rato"
        raise ShopError(self._blocked_why)

    def _check(self, page: Page) -> None:
        if page.status == 429:
            self._block("HTTP 429 (demasiadas peticiones)")
        if page.status in (403, 503):
            head = page.content[:4000].decode("utf-8", "replace").lower()
            if any(mark in head for mark in _CHALLENGE):
                self._block(f"HTTP {page.status} con página de comprobación (captcha)")
        if page.status == 403:
            self._forbidden += 1
            if self._forbidden >= 2:
                self._block("HTTP 403 seguidos (la tienda bloquea las peticiones)")
            raise ShopError("HTTP 403")
        self._forbidden = 0
