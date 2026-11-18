"""El recorrido del catálogo entero: pausas, topes, avance y cancelación.

La consulta semanal de una tienda lee TODAS las páginas de cada sección activa (solo datos: nombre,
precio, color, marca, referencia y lo necesario para pedir la ficha después; nada de fotos). Son
muchas más páginas que antes, así que va despacio: de noche, con pausas largas y algo de variación
entre una página y la siguiente, para no ir a ritmo de metrónomo.

Quien consulta abre un `Crawl` para la tienda (`running`); los conectores, antes de pedir cada página
del listado, llaman a `before_page()` (espera su turno y mira si se ha cancelado) y, al leerla, a
`page_read(n)` (para el avance que se ve en el panel «Tiendas»). Fuera de una consulta (el buscador,
«Ver más», los tests que llaman al conector a pelo) no hay pausas extra y valen los topes por defecto.

Los topes son de seguridad (que un fallo no deje el recorrido dando vueltas), no de catálogo: altos y
configurables por tienda (`ARMARIO_SHOP_MAX_PAGES`, `ARMARIO_SHOP_MAX_PAGES_ZARA`…).
"""
import random
import threading
import time
from contextlib import contextmanager

from ... import config
from .base import ShopError


class Cancelled(ShopError):
    """El usuario ha cancelado la consulta desde el panel. Lo leído hasta ahí se guarda."""


class Partial(ShopError):
    """Una sección se ha leído solo en parte: `products` es lo leído y `cause`, por qué se paró (un
    fallo de la tienda, un bloqueo o la cancelación). Quien consulta guarda lo leído, pero la sección
    no cuenta como completa: no se retira nada de ella y la próxima vez se vuelve a leer."""

    def __init__(self, products: list, cause: Exception):
        super().__init__(str(cause))
        self.products = products
        self.cause = cause


class Crawl:
    """El recorrido de UNA tienda. `progress` es un dict compartido que lee el panel (ver
    `shopping.crawl_progress`)."""

    def __init__(self, store: str, pause: tuple[float, float] = (0.0, 0.0), max_pages: int | None = None,
                 max_products: int | None = None, cancel: threading.Event | None = None,
                 progress: dict | None = None):
        self.store = store
        self.pause = pause
        self.max_pages = max_pages if max_pages is not None else config.shop_limit(store, "PAGES")
        self.max_products = max_products if max_products is not None else config.shop_limit(store, "PRODUCTS")
        self.cancel = cancel or threading.Event()
        self.progress = progress if progress is not None else {}
        self.progress.setdefault("pages", 0)
        self.progress.setdefault("products", 0)
        self._last: float | None = None

    def check(self) -> None:
        if self.cancel.is_set():
            raise Cancelled("consulta cancelada")

    def before_page(self) -> None:
        """Espera su turno (la pausa desde la última página, con algo de variación) mirando a trozos si
        se cancela. La primera página no espera."""
        self.check()
        if self._last is not None and self.pause[1] > 0:
            until = self._last + random.uniform(*self.pause)
            while (left := until - time.monotonic()) > 0:
                if self.cancel.wait(min(left, 0.5)):
                    break
        self.check()

    def page_read(self, products: int) -> None:
        self.progress["pages"] = self.progress.get("pages", 0) + 1
        self.progress["section_pages"] = self.progress.get("section_pages", 0) + 1
        self.progress["products"] = self.progress.get("products", 0) + max(0, products)
        self._last = time.monotonic()
        self.update()

    # --- el avance, en pasos: una página del listado o una ficha (con sus fotos) de las finalistas

    def start_sections(self, total: int, done: int = 0) -> None:
        self.progress.update(sections_total=total, sections_done=done, done_section_pages=[])
        self.update()

    def section_start(self, slug: str, label: str) -> None:
        self.progress.update(section=slug, section_label=label, section_pages=0, section_pages_total=None)
        self.update()

    def section_total(self, pages: int | None) -> None:
        """La tienda ha dicho cuántas páginas tiene la sección (JD) o se puede calcular (Pull&Bear)."""
        self.progress["section_pages_total"] = max(1, int(pages)) if pages else None
        self.update()

    def section_end(self, skipped: bool = False) -> None:
        if not skipped:
            self.progress.setdefault("done_section_pages", []).append(self.progress.get("section_pages", 0))
        self.progress["sections_done"] = self.progress.get("sections_done", 0) + 1
        self.progress.update(section=None, section_label=None, section_pages=0, section_pages_total=None)
        self.update()

    def phase(self, name: str, steps: int = 0) -> None:
        """Otra fase: «catalogo», «propuestas» (`steps` fichas por bajar) o «traduciendo»."""
        self.progress["phase"] = name
        if name == "propuestas":
            self.progress.update(promote_total=max(0, steps), promote_done=0)
        self.update()

    def step(self) -> None:
        """Una ficha (con sus fotos) de las finalistas, hecha."""
        self.progress["promote_done"] = self.progress.get("promote_done", 0) + 1
        self.update()

    def update(self) -> None:
        """Recalcula el porcentaje (que nunca retrocede) y el tiempo que queda (al ritmo medido)."""
        done, total, known = estimate(self.progress)
        percent = 100.0 * done / total if total else 0.0
        self.progress["steps_done"], self.progress["steps_total"] = done, total
        self.progress["known"] = known
        # Mientras el total es una suposición no se avanza: si luego resultara mayor, la barra tendría
        # que esperar parada demasiado rato.
        if known:
            self.progress["percent"] = round(min(99.0, max(self.progress.get("percent", 0.0), percent)), 1)
        else:
            self.progress.setdefault("percent", 0.0)
        started = self.progress.setdefault("_t0", time.monotonic())
        elapsed = time.monotonic() - started
        left = max(0, total - done)
        self.progress["eta_seconds"] = round(elapsed / done * left) if done >= 2 and known else None


DEFAULT_SECTION_PAGES = 5  # páginas que se suponen a una sección mientras no se sepa nada mejor
PROMOTE_GUESS = 15  # fichas que se suponen para la fase de propuestas antes de saberlo


def estimate(progress: dict) -> tuple[int, int, bool]:
    """(pasos hechos, pasos totales estimados, si el total se conoce de verdad) a partir del avance.

    Un paso es una página del listado o una ficha de las finalistas. Lo que ya está leído cuenta lo que
    fue; la sección en curso, las páginas que la tienda dice (si lo dice) o, si no, la media de las ya
    leídas; las que faltan, esa misma media; y la fase de propuestas, las fichas que se van a bajar.
    `known` es False si todavía no hay ninguna medida (ni secciones leídas ni total de la tienda)."""
    done_pages = list(progress.get("done_section_pages") or [])
    sections_total = int(progress.get("sections_total") or 0)
    sections_done = int(progress.get("sections_done") or 0)
    current = int(progress.get("section_pages") or 0)
    current_total = progress.get("section_pages_total")
    average = (sum(done_pages) / len(done_pages)) if done_pages else None
    per_section = average if average else (current_total or DEFAULT_SECTION_PAGES)
    in_section = progress.get("section") is not None
    current_est = max(current + (0 if current_total else 1), current_total or round(per_section)) if in_section else 0
    future = max(0, sections_total - sections_done - (1 if in_section else 0))
    catalog_total = sum(done_pages) + current_est + round(future * per_section)
    catalog_done = sum(done_pages) + current
    phase = progress.get("phase")
    if phase in ("eligiendo", "propuestas"):
        catalog_total = catalog_done = sum(done_pages) + current
    promote_total = int(progress.get("promote_total") or 0) if phase == "propuestas" else PROMOTE_GUESS
    promote_done = int(progress.get("promote_done") or 0)
    total = max(1, catalog_total + promote_total)
    known = bool(done_pages) or bool(current_total) or phase in ("eligiendo", "propuestas")
    return min(total, catalog_done + promote_done), total, known


_local = threading.local()


def current() -> Crawl | None:
    return getattr(_local, "crawl", None)


@contextmanager
def running(crawl: Crawl):
    """Dentro, los conectores de este hilo hacen sus pausas y apuntan su avance en `crawl`."""
    before = current()
    _local.crawl = crawl
    try:
        yield crawl
    finally:
        _local.crawl = before


def before_page() -> None:
    crawl = current()
    if crawl is not None:
        crawl.before_page()


def page_read(products: int) -> None:
    crawl = current()
    if crawl is not None:
        crawl.page_read(products)


def max_pages(store: str) -> int:
    crawl = current()
    return crawl.max_pages if crawl is not None else config.shop_limit(store, "PAGES")


def max_products(store: str) -> int:
    crawl = current()
    return crawl.max_products if crawl is not None else config.shop_limit(store, "PRODUCTS")


def section_total(pages: int | None) -> None:
    crawl = current()
    if crawl is not None:
        crawl.section_total(pages)


def check() -> None:
    crawl = current()
    if crawl is not None:
        crawl.check()
