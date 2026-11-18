"""Un Chromium de verdad, con su ventana, para las tiendas que no se dejan leer de otra forma
(Pull&Bear y Bershka: a httpx les responden con un desafío de JavaScript y a un Chromium sin
ventana con «Access Denied»; JD Sports: desde el Umbrel responde 403 a curl y a httpx en casi todo;
Snipes y size?: el listado lo pide la propia página; Jules y Bonobo: Cloudflare da 403 a httpx, y en
Bonobo también a las fotos, que se abren en otra pestaña de la misma sesión: `image`; Uniqlo, Mango, H&M,
COS y Weekday: Akamai o Vercel, y solo se lee su listado; para sus páginas siguientes, `more` pulsa el
botón de la propia web o baja hasta el final, como un usuario).

Lo acordado con el usuario, sin excepciones:

- Solo el Chromium de serie de Playwright, con su ventana. Nada de complementos «stealth», ni
  parches que oculten que está automatizado, ni `navigator.webdriver` tocado, ni huellas falsas,
  ni proxys, ni resolver o rodear captchas.
- Si la tienda responde con «Access Denied», un captcha o cualquier desafío que no se resuelva solo
  al cargar, se PARA con esa tienda (BlockedError) y no se le vuelve a preguntar hasta el día
  siguiente. El motivo va en claro al panel «Tiendas».
- Solo catálogo público: ni sesión, ni carrito, ni compra. El aviso de cookies se rechaza si sale
  (solo las imprescindibles) y si no, se ignora: lo que se lee son las respuestas JSON de la página
  (Pull&Bear, Bershka) o el JSON que la página ya trae dentro (`page_json`, JD Sports).
- Con educación: una página o una petición cada vez, con 2-3 s entre ellas.

Cómo se usa: el navegador solo vive mientras dura una consulta en segundo plano. Quien lanza la
tanda abre una `session()` (no arranca nada todavía); el conector pide `page(...)` y solo entonces
se abre Chromium; al salir de la sesión se cierra pase lo que pase. Fuera de una sesión (una petición
HTTP normal) no se abre nunca: `require` lanza ShopError. Un cerrojo impide dos navegadores a la vez.

En Linux (Docker, Umbrel) no hay pantalla: se arranca una virtual (Xvfb) solo para esa sesión.
En Windows, la ventana normal, colocada fuera de la vista.

Playwright es opcional (importación perezosa): sin él o sin Chromium, `missing()` lo dice y esas
tiendas salen como «No disponible» sin tocar al resto de la app.
"""
import glob
import importlib.util
import itertools
import json
import logging
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from .base import BlockedError, BrowserUnavailable, ShopError

log = logging.getLogger("armario.compras.navegador")

PAUSE = (2.0, 3.0)  # segundos entre una página o petición y la siguiente
LAUNCH_TIMEOUT_MS = 60_000
NAV_TIMEOUT_MS = 60_000
FETCH_TIMEOUT_MS = 45_000
WAIT_JSON_SECONDS = 30.0  # lo que se espera a que la página pida su catálogo
WAIT_SCRIPT_SECONDS = 10.0  # lo que se espera a que aparezcan los datos de la página (JD Sports)
LOCK_SECONDS = 120.0  # lo que se espera a que se cierre otro navegador antes de rendirse
VIEWPORT = {"width": 1280, "height": 900}

NO_START_TEXT = "el navegador no arranca en este equipo; la tienda no se ha llegado a consultar"
BLOCKED_TEXT = "la tienda ha bloqueado el acceso"
CAPTCHA_TEXT = "la tienda pide un captcha"
_ACCESS_DENIED = ("access denied", "accès refusé", "acceso denegado", "you don't have permission")
_CAPTCHA_WORDS = ("captcha", "are you a robot", "êtes-vous un robot", "verify you are human",
                  "vérifiez que vous", "pardon our interruption", "unusual traffic")
_CAPTCHA_FRAMES = ("captcha-delivery", "hcaptcha", "recaptcha", "challenges.cloudflare", "px-captcha", "arkoselabs")
_COOKIE_REJECT = ("#onetrust-reject-all-handler", "button:has-text('Continuer sans accepter')",
                  "button:has-text('Tout refuser')", "button:has-text('Refuser')")

_launch_lock = threading.Lock()  # nunca dos navegadores a la vez
_local = threading.local()
_ids = itertools.count(1)
_blocked: dict[str, tuple[date, str]] = {}  # tienda -> (día, motivo): hoy no se le pregunta más


# ---------- ¿Está instalado?


def _browsers_dir() -> Path:
    custom = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if custom and custom != "0":
        return Path(custom)
    if custom == "0":  # los navegadores dentro del propio paquete
        spec = importlib.util.find_spec("playwright")
        base = Path(spec.origin).parent if spec and spec.origin else Path(".")
        return base / "driver" / "package" / ".local-browsers"
    if sys.platform.startswith("win"):
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ms-playwright"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "ms-playwright"


def missing() -> str | None:
    """None si se puede abrir el navegador; si no, el motivo para el panel."""
    if importlib.util.find_spec("playwright") is None:
        return "No disponible: falta el navegador"
    if not glob.glob(str(_browsers_dir() / "chromium-*")):
        return "No disponible: falta el navegador"
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY") and not shutil.which("Xvfb"):
        return "No disponible: falta la pantalla virtual (Xvfb)"
    return None


def _short(exc: Exception) -> str:
    """La primera línea del error, corta: Playwright explica bien qué falta («Host system is missing
    dependencies», «Executable doesn't exist»), y eso es lo que hay que ver en el panel."""
    first = next((line.strip() for line in str(exc).splitlines() if line.strip()), "")
    first = re.sub(r"^\w+\.\w+: ", "", first)  # «BrowserType.launch: …»
    return f"{type(exc).__name__}: {first[:140]}" if first else type(exc).__name__


# ---------- Bloqueos: hoy no se insiste


def _today() -> date:
    from .. import outfits  # aquí: la fecha de «hoy» en la zona del usuario

    return outfits.local_today()


def blocked(store: str) -> str | None:
    """El motivo si la tienda ha bloqueado hoy (en este proceso); None si no."""
    entry = _blocked.get(store)
    return entry[1] if entry and entry[0] == _today() else None


def block(store: str, why: str) -> BlockedError:
    """Apunta que la tienda ha bloqueado hoy y devuelve el error para lanzarlo."""
    message = f"{why} (no se vuelve a intentar hasta mañana)"
    _blocked[store] = (_today(), message)
    log.warning("Compras: %s bloquea: %s", store, why)
    return BlockedError(message)


def forget_blocks() -> None:
    _blocked.clear()


# ---------- La sesión


def active() -> bool:
    """¿Hay una sesión de navegador abierta en este hilo (una consulta en segundo plano)?"""
    return getattr(_local, "session", None) is not None


def current() -> "Session | None":
    return getattr(_local, "session", None)


@contextmanager
def session():
    """Marca el trabajo de una consulta en segundo plano: dentro, los conectores pueden abrir el
    navegador (solo si lo necesitan). Al salir se cierra todo, falle lo que falle."""
    if active():  # anidada: la de fuera manda
        yield _local.session
        return
    opened = Session()
    _local.session = opened
    try:
        yield opened
    finally:
        _local.session = None
        opened.close()


def require(store: str) -> "Session":
    """La sesión de este hilo, lista para hablar con la tienda. Lanza ShopError si no hay sesión (una
    petición HTTP normal), si falta el navegador o si la tienda ha bloqueado hoy."""
    opened = current()
    if opened is None:
        raise ShopError("esta tienda solo se lee con navegador, en las consultas en segundo plano")
    already = blocked(store)
    if already:
        raise BlockedError(already)
    why = missing()
    if why:
        raise BrowserUnavailable(why)
    return opened


class Response:
    """Una respuesta JSON que la página pidió por su cuenta."""

    def __init__(self, url: str, status: int, data):
        self.url, self.status, self.data = url, status, data


class Session:
    def __init__(self):
        self.id = next(_ids)
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._image_page = None  # otra pestaña, solo para abrir fotos (`image`)
        self._xvfb: subprocess.Popen | None = None
        self._locked = False
        self._failed = ""
        self._last = 0.0
        self.pages = 0  # páginas abiertas en esta sesión (para el registro)
        self.fetches = 0

    # --- arrancar y cerrar

    def _start(self):
        if self._page is not None:
            return self._page
        if self._failed:  # ya no arrancó en esta sesión: no se reintenta en cada sección
            raise BrowserUnavailable(self._failed)
        try:
            return self._launch()
        except BrowserUnavailable as exc:
            self._failed = str(exc)
            raise

    def _launch(self):
        if not _launch_lock.acquire(timeout=LOCK_SECONDS):
            raise BrowserUnavailable("hay otro navegador abierto: se deja para la próxima")
        self._locked = True
        started = time.monotonic()
        try:
            from playwright.sync_api import sync_playwright  # perezoso: la dependencia es opcional

            env = dict(os.environ)
            args = [f"--window-size={VIEWPORT['width']},{VIEWPORT['height'] + 120}"]
            if sys.platform.startswith("linux"):
                args.append("--disable-dev-shm-usage")  # el /dev/shm de Docker es pequeño
                if not env.get("DISPLAY"):
                    env["DISPLAY"] = self._start_display()
            elif sys.platform.startswith("win"):
                args.append("--window-position=-2400,40")  # fuera de la vista, sin más
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=False, args=args, env=env, timeout=LAUNCH_TIMEOUT_MS)
            self._context = self._browser.new_context(locale="fr-FR", viewport=VIEWPORT)
            self._context.set_default_timeout(NAV_TIMEOUT_MS)
            self._page = self._context.new_page()
        except ShopError as exc:  # la pantalla virtual
            self.close()
            raise BrowserUnavailable(f"{NO_START_TEXT} ({exc})") from exc
        except Exception as exc:
            self.close()
            log.exception("Compras: no se pudo abrir el navegador")
            # Distinto de un bloqueo: aquí la tienda ni se ha tocado, es el navegador de este equipo.
            raise BrowserUnavailable(f"{NO_START_TEXT} ({_short(exc)})") from exc
        log.info("Compras: navegador abierto en %.1f s", time.monotonic() - started)
        return self._page

    def _start_display(self) -> str:
        """Una pantalla virtual solo para esta sesión. Devuelve su DISPLAY (":99")."""
        binary = shutil.which("Xvfb")
        if binary is None:
            raise ShopError("No disponible: falta la pantalla virtual (Xvfb)")
        for number in range(99, 130):
            if os.path.exists(f"/tmp/.X{number}-lock"):
                continue
            proc = subprocess.Popen(
                [binary, f":{number}", "-screen", "0", "1366x1024x24", "-nolisten", "tcp"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            for _ in range(50):
                if os.path.exists(f"/tmp/.X11-unix/X{number}") or proc.poll() is not None:
                    break
                time.sleep(0.1)
            if proc.poll() is None:
                self._xvfb = proc
                return f":{number}"
        raise ShopError("no se pudo arrancar la pantalla virtual (Xvfb)")

    def close(self) -> None:
        for step in (
            lambda: self._context and self._context.close(),
            lambda: self._browser and self._browser.close(),
            lambda: self._pw and self._pw.stop(),
        ):
            try:
                step()
            except Exception:  # cerrar nunca falla hacia fuera
                log.debug("Compras: fallo al cerrar el navegador", exc_info=True)
        self._page = self._image_page = self._context = self._browser = self._pw = None
        if self._xvfb is not None:
            try:
                self._xvfb.terminate()
                self._xvfb.wait(timeout=5)
            except Exception:
                try:
                    self._xvfb.kill()
                except Exception:
                    pass
            self._xvfb = None
        if self._locked:
            self._locked = False
            _launch_lock.release()
            log.info("Compras: navegador cerrado (%s páginas, %s peticiones)", self.pages, self.fetches)

    # --- lo que usan los conectores

    def _wait_turn(self) -> None:
        wait = self._last + random.uniform(*PAUSE) - time.monotonic()
        if wait > 0:
            time.sleep(wait)

    def host(self) -> str:
        """La dirección de la página abierta ("" si aún no hay ninguna)."""
        try:
            return self._page.url if self._page is not None else ""
        except Exception:
            return ""

    def open(self, store: str, url: str, want, ready, wait: float = WAIT_JSON_SECONDS) -> list[Response]:
        """Abre una página de la tienda y devuelve las respuestas JSON que ella misma pide y que
        interesan (`want(url)`), esperando hasta que `ready(urls)` diga que ya están. Lanza
        BlockedError si la tienda bloquea o pide un captcha, y ShopError si no carga."""
        page = self._start()
        self._wait_turn()
        seen: list = []

        def on_response(response) -> None:
            try:
                if want(response.url):
                    seen.append(response)
            except Exception:
                pass

        page.on("response", on_response)
        try:
            self.pages += 1
            try:
                main = page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            except Exception as exc:
                raise ShopError(f"la página no cargó ({type(exc).__name__})") from exc
            finally:
                self._last = time.monotonic()
            self._check(store, page, main.status if main else None)
            deadline = time.monotonic() + wait
            while time.monotonic() < deadline and not ready([r.url for r in seen]):
                page.wait_for_timeout(250)
            self._reject_cookies(page)
            responses = self._collect(store, seen)
            if not ready([r.url for r in responses]):
                self._check(store, page, None, strict=True)
            return responses
        finally:
            page.remove_listener("response", on_response)
            self._last = time.monotonic()

    def _collect(self, store: str, seen: list) -> list[Response]:
        """Las respuestas oídas, ya leídas como JSON. Un 403 o un 429 en lo que interesa es un bloqueo."""
        responses = []
        for response in list(seen):
            try:
                status = response.status
                data = json.loads(response.body()) if status == 200 else None
            except Exception:
                status, data = response.status, None
            if status in (403, 429):
                raise block(store, BLOCKED_TEXT)
            responses.append(Response(response.url, status, data))
        return responses

    def more(self, store: str, want, ready, click: str | None = None, wait: float = WAIT_JSON_SECONDS) -> list[Response]:
        """En la página ya abierta, lo que haría un usuario para ver más productos: pulsar el botón de la
        propia web (`click`, un selector: «Charger la page suivante» en COS) o, sin él, bajar hasta el final
        poco a poco (las que cargan al llegar abajo: Uniqlo, Mango). Devuelve las respuestas JSON nuevas
        que pide la página y que interesan (`want`), esperando hasta que `ready(urls)` diga que ya están.
        Sin botón (ya no hay más) o sin nada nuevo, una lista vacía. Lanza BlockedError si la tienda bloquea."""
        page = self._page
        if page is None:
            raise ShopError("no hay ninguna página abierta")
        self._wait_turn()
        seen: list = []

        def on_response(response) -> None:
            try:
                if want(response.url):
                    seen.append(response)
            except Exception:
                pass

        page.on("response", on_response)
        try:
            self.pages += 1
            try:
                if click:
                    button = page.locator(click).first
                    if button.count() == 0:
                        return []
                    button.scroll_into_view_if_needed(timeout=5000)
                    if not button.is_visible(timeout=2000) or not button.is_enabled(timeout=2000):
                        return []
                    button.click(timeout=5000)
                else:
                    # Hasta abajo a trozos de pantalla, como con la rueda: la web carga al llegar al final.
                    for _ in range(12):
                        at_end = page.evaluate(
                            "() => { window.scrollBy(0, Math.round(window.innerHeight * 0.9));"
                            " return window.innerHeight + window.scrollY >= document.body.scrollHeight - 4; }")
                        page.wait_for_timeout(350)
                        if at_end:
                            break
            except ShopError:
                raise
            except Exception as exc:
                raise ShopError(f"la página no respondió ({type(exc).__name__})") from exc
            deadline = time.monotonic() + wait
            while time.monotonic() < deadline and not ready([r.url for r in seen]):
                page.wait_for_timeout(250)
            responses = self._collect(store, seen)
            if not responses:
                self._check(store, page, None)
            return responses
        finally:
            page.remove_listener("response", on_response)
            self._last = time.monotonic()

    def evaluate(self, store: str, expression: str, arg=None):
        """Lee algo de la página ya abierta (los datos que trae dentro: el `self.__next_f` de Mango). No
        pide nada a la tienda. Lanza ShopError si no hay página o si falla."""
        if self._page is None:
            raise ShopError("no hay ninguna página abierta")
        try:
            return self._page.evaluate(expression, arg)
        except Exception as exc:
            raise ShopError(f"la página no se pudo leer ({type(exc).__name__})") from exc

    def page_json(self, store: str, url: str, script_id: str = "__NEXT_DATA__",
                  wait: float = WAIT_SCRIPT_SECONDS) -> tuple[int | None, object]:
        """Abre una página de la tienda y devuelve (estado, JSON del `<script id=script_id>` que trae
        la propia página). Es lo que pinta el servidor (JD Sports, con Next.js): no se lee nada más.
        Un 404 o un 410 se devuelven tal cual, con None (el producto ya no existe). Lanza BlockedError
        si la tienda bloquea o pide un captcha, y ShopError si la página no carga o no trae sus datos."""
        page = self._start()
        self._wait_turn()
        self.pages += 1
        try:
            try:
                main = page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            except Exception as exc:
                raise ShopError(f"la página no cargó ({type(exc).__name__})") from exc
            status = main.status if main else None
            if status in (404, 410):
                return status, None
            self._check(store, page, status)
            text = None
            deadline = time.monotonic() + wait
            while True:
                try:
                    text = page.evaluate("(id) => document.getElementById(id)?.textContent ?? null", script_id)
                except Exception:  # la página se está recargando sola (una comprobación que se resuelve)
                    text = None
                if text is not None or time.monotonic() >= deadline:
                    break
                page.wait_for_timeout(500)
            if text is None:
                self._check(store, page, None, strict=True, missing="la página no traía sus datos")
            try:
                return status, json.loads(text)
            except ValueError as exc:
                raise ShopError("la respuesta no era la esperada (datos ilegibles)") from exc
        finally:
            self._last = time.monotonic()

    def page_html(self, store: str, url: str) -> tuple[int | None, str | None]:
        """Abre una página de la tienda y devuelve (estado, HTML de la página ya cargada). Es para las
        tiendas que hoy se leen sin navegador (Nike, Jack & Jones, Carhartt WIP) si un día dejan de
        responder a un cliente normal: su conector lee del HTML lo mismo que lee ahora. Un 404 o un 410
        se devuelven tal cual, con None. Lanza BlockedError si la tienda bloquea o pide un captcha."""
        page = self._start()
        self._wait_turn()
        self.pages += 1
        try:
            try:
                main = page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            except Exception as exc:
                raise ShopError(f"la página no cargó ({type(exc).__name__})") from exc
            status = main.status if main else None
            if status in (404, 410):
                return status, None
            self._check(store, page, status)
            try:
                return status, page.content()
            except Exception as exc:
                raise ShopError(f"la página no se pudo leer ({type(exc).__name__})") from exc
        finally:
            self._last = time.monotonic()

    def _fetch(self, store: str, url: str, accept: str) -> tuple[int, str]:
        """(estado, texto) de `url` pedida desde dentro de la página abierta (mismo origen, como hace la
        propia web). Lanza BlockedError si la tienda bloquea."""
        page = self._start()
        self._wait_turn()
        try:
            self.fetches += 1
            status, text = page.evaluate(
                """async ([u, accept]) => {
                    const ctrl = new AbortController();
                    const timer = setTimeout(() => ctrl.abort(), 40000);
                    try {
                        const r = await fetch(u, {credentials: 'include', signal: ctrl.signal,
                                                  headers: {'Accept': accept}});
                        return [r.status, await r.text()];
                    } catch (e) { return [0, String(e)]; } finally { clearTimeout(timer); }
                }""",
                [url, accept],
            )
        except Exception as exc:
            raise ShopError(f"la petición falló ({type(exc).__name__})") from exc
        finally:
            self._last = time.monotonic()
        if status in (403, 429):
            raise block(store, BLOCKED_TEXT)
        if status == 0:
            raise ShopError("no se pudo conectar")
        return status, text or ""

    def fetch_json(self, store: str, url: str) -> tuple[int, object]:
        """Pide `url` desde dentro de la página abierta (mismo origen, como hace la propia web).
        Devuelve (estado, JSON o None). Lanza BlockedError si la tienda bloquea."""
        status, text = self._fetch(store, url, "application/json")
        try:
            data = json.loads(text) if status == 200 else None
        except ValueError:
            low = (text or "")[:3000].lower()
            if any(word in low for word in _CAPTCHA_WORDS):
                raise block(store, CAPTCHA_TEXT) from None
            raise ShopError("la respuesta no era la esperada (no es JSON)") from None
        return status, data

    def fetch_text(self, store: str, url: str) -> tuple[int, str]:
        """Como `fetch_json`, para lo que la web pide en HTML (el «Afficher plus» de las tiendas de
        Salesforce, Jules y Bonobo: `Search-UpdateGrid` devuelve trozos de HTML). Una página de
        comprobación en vez de lo pedido es un captcha: se para con la tienda."""
        status, text = self._fetch(store, url, "text/html, */*; q=0.01")
        head = text[:3000].lower()
        # Una rejilla de verdad es larga; una página de comprobación, corta (o no es un 200).
        suspicious = status != 200 or len(text) < 20_000
        if suspicious and (any(word in head for word in _CAPTCHA_WORDS) or "just a moment" in head or "cf-chl" in head):
            raise block(store, CAPTCHA_TEXT)
        return status, text

    def image(self, store: str, url: str) -> bytes:
        """Los bytes de una foto abierta como página, en otra pestaña de la misma sesión (Bonobo: su CDN
        no responde a un cliente normal ni a las peticiones sueltas del navegador, pero sí a la foto
        abierta en él). La pestaña de la tienda no se mueve. Lanza ShopError si no llega."""
        self._start()
        self._wait_turn()
        try:
            if self._image_page is None:
                self._image_page = self._context.new_page()
            self.pages += 1
            try:
                response = self._image_page.goto(url, wait_until="load", timeout=NAV_TIMEOUT_MS)
            except Exception as exc:
                raise ShopError(f"la foto no cargó ({type(exc).__name__})") from exc
            status = response.status if response else None
            if status in (403, 429):
                raise block(store, BLOCKED_TEXT)
            kind = (response.headers.get("content-type") or "") if response else ""
            if status != 200 or not kind.startswith("image/"):
                raise ShopError(f"HTTP {status} al bajar la foto")
            try:
                return response.body()
            except Exception as exc:
                raise ShopError(f"la foto no se pudo leer ({type(exc).__name__})") from exc
        finally:
            self._last = time.monotonic()

    # --- por dentro

    def _check(self, store: str, page, status: int | None, strict: bool = False,
               missing: str = "la página no pidió su catálogo") -> None:
        """¿Ha bloqueado la tienda? «Access Denied» o un 403/429 en la página: bloqueo. Un captcha o
        un desafío que no se ha resuelto solo: captcha. Con `strict` (la página no ha pedido su
        catálogo) cualquier pista vale; si no, solo las claras."""
        try:
            title = (page.title() or "").lower()
            text = (page.inner_text("body", timeout=5000) or "")[:4000].lower()
        except Exception:
            title, text = "", ""
        if status in (403, 429) or any(word in title or word in text[:600] for word in _ACCESS_DENIED):
            raise block(store, BLOCKED_TEXT)
        frames = " ".join(frame.url.lower() for frame in page.frames)
        if any(mark in frames for mark in _CAPTCHA_FRAMES):
            raise block(store, CAPTCHA_TEXT)
        if (strict or len(text) < 1500) and any(word in title or word in text for word in _CAPTCHA_WORDS):
            raise block(store, CAPTCHA_TEXT)
        if strict:
            raise ShopError(missing)

    def _reject_cookies(self, page) -> None:
        """Si sale el aviso de cookies, solo las imprescindibles. Si no sale, nada."""
        for selector in _COOKIE_REJECT:
            try:
                button = page.locator(selector).first
                if button.is_visible(timeout=500):
                    button.click(timeout=2000)
                    return
            except Exception:
                continue
