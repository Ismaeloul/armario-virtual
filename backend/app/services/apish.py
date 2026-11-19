"""Cliente de API.SH (https://api.sh), el servicio de scraping de pago que ha contratado el usuario.

Excepción decidida por él el 19-11-2026: Uniqlo bloquea nuestro Chromium (Akamai). De momento solo la usa
Uniqlo, pero es COMÚN: cualquier conector que lo use lo marca con `uses_apish = True` y llama a `get()`. Lo
que hay aquí:

- La clave (`x-api-key`) es UNA para toda la app: se pega en Ajustes («API.SH»; `PUT /api/settings/apish-key`)
  y se guarda cifrada con `vault` (`ARMARIO_APISH_KEY` manda en desarrollo). Sin clave no se llama nunca. La
  clave no aparece en ningún mensaje, log ni excepción: va solo en la cabecera, y cualquier texto que devuelva
  el servicio se limpia por si la repitiera.
- Créditos: cada llamada cuesta lo que dice `credits_used` de su respuesta (1 por búsqueda o ficha; según
  su documentación, las respuestas en caché cuestan lo mismo y los errores de su lado no cuestan). Se apuntan
  en un contador mensual COMÚN a todas las tiendas (hora de casa, `ARMARIO_TZ`; `settings`, `apish_credits`).
  Antes de cada llamada se mira el tope (`ARMARIO_APISH_MONTHLY_CREDITS`, 300 por defecto, para no pasar de
  los 1.000 gratis de la cuenta): si ya está, no se llama y las tiendas de API.SH paran hasta el mes siguiente.
- `raw=0` en todas las llamadas: quita los bloques `raw`, que no se usan (no cambia el coste; la respuesta
  pesa mucho menos).
"""
import json
import logging
import os
import threading
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import time

import httpx

from .. import config
from .shops.base import BlockedError, ShopError

log = logging.getLogger(__name__)

SECRET = "apish"  # nombre de la clave en el vault
K_CREDITS = "apish_credits"  # {"month": "2026-11", "used": 12}
MISSING_KEY = "Falta la clave de API: pégala en Ajustes, en «API.SH»"
_MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
           "noviembre", "diciembre"]

_lock = threading.Lock()
# Los tests ponen aquí un `httpx.MockTransport`: así ninguna llamada sale a la red.
transport: httpx.BaseTransport | None = None


class QuotaReached(BlockedError):
    """El tope de créditos del mes (el nuestro o el de la cuenta de API.SH): no se llama más hasta el mes
    siguiente. Es un BlockedError para que la consulta pare con esta tienda en vez de seguir sección a sección."""


# ---------- Ajustes (con su propia sesión: los conectores no reciben la de la petición)


def _session():
    from ..db import SessionLocal

    return SessionLocal()


def read_setting(key: str, default=None):
    from ..models import Setting

    with _session() as db:
        row = db.get(Setting, key)
        if row is None:
            return default
        try:
            return json.loads(row.value)
        except ValueError:
            return default


def write_setting(key: str, value) -> None:
    from ..models import Setting

    with _session() as db:
        db.merge(Setting(key=key, value=json.dumps(value, ensure_ascii=False)))
        db.commit()


def month_now() -> str:
    try:
        now = datetime.now(ZoneInfo(os.environ.get("ARMARIO_TZ", "Europe/Paris")))
    except (ZoneInfoNotFoundError, ValueError, OSError):
        now = datetime.now()
    return now.strftime("%Y-%m")


def next_month_text(month: str) -> str:
    """«2026-11» -> «el 1 de diciembre»."""
    year, number = (int(part) for part in month.split("-"))
    return f"el 1 de {_MONTHS[number % 12]}"


# ---------- La clave


def api_key() -> str | None:
    from . import vault

    with _session() as db:
        return vault.get(db, SECRET)


def has_key() -> bool:
    return api_key() is not None


def status() -> dict:
    """Para Ajustes: si hay clave (nunca la clave), si viene del entorno y los créditos del mes."""
    from . import vault

    used, limit = credits()
    return {"has_key": has_key(), "from_env": vault.from_env(SECRET), "credits_used": used, "credits_limit": limit}


# ---------- Créditos


def credits() -> tuple[int, int]:
    """(créditos usados este mes, tope del mes)."""
    stored = read_setting(K_CREDITS, {}) or {}
    used = int(stored.get("used", 0) or 0) if stored.get("month") == month_now() else 0
    return used, config.APISH_MONTHLY_CREDITS


def _spend(amount: int) -> None:
    if amount <= 0:
        return
    month = month_now()
    stored = read_setting(K_CREDITS, {}) or {}
    used = int(stored.get("used", 0) or 0) if stored.get("month") == month else 0
    write_setting(K_CREDITS, {"month": month, "used": used + amount})


def quota_text(used: int, limit: int) -> str:
    return (f"Tope de créditos del mes alcanzado ({used} de {limit}): no se consulta hasta "
            f"{next_month_text(month_now())}")


def missing() -> str | None:
    """Por qué no se puede llamar ahora a API.SH (sin clave o con el tope del mes), o None si se puede.
    No llama a nada."""
    if not has_key():
        return MISSING_KEY
    used, limit = credits()
    if used >= limit:
        return quota_text(used, limit)
    return None


# ---------- El saldo real (gratis)

_ACCOUNT_TTL = 300  # segundos: Ajustes se abre a menudo y el saldo no cambia tan rápido
_account_cache: dict = {}


def account() -> dict | None:
    """El saldo de verdad de la cuenta de API.SH (`GET /v1/account`, gratis: no gasta créditos):
    {"total", "free", "plan", "payg", "free_resets_at", "spent_month"}. None si no hay clave o no
    responde. Se guarda unos minutos en memoria. Nunca lanza ni deja ver la clave."""
    key = api_key()
    if not key:
        return None
    now = time.monotonic()
    cached = _account_cache.get("value")
    if cached is not None and _account_cache.get("key") == hash(key) and now - _account_cache.get("at", 0) < _ACCOUNT_TTL:
        return cached
    try:
        with httpx.Client(timeout=15, transport=transport) as client:
            response = client.get(config.APISH_BASE + "/v1/account", headers={"x-api-key": key})
        body = response.json() if response.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        body = None
    if not isinstance(body, dict):
        return None
    credits_ = body.get("credits") if isinstance(body.get("credits"), dict) else {}
    spend = body.get("spend") if isinstance(body.get("spend"), dict) else {}

    def number(value):
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    value = {
        "total": number(credits_.get("total")),
        "free": number(credits_.get("free")),
        "plan": number(credits_.get("plan")),
        "payg": number(credits_.get("payg")),
        "free_resets_at": credits_.get("free_resets_at") if isinstance(credits_.get("free_resets_at"), str) else None,
        "spent_month": number(spend.get("this_month")),
    }
    if value["total"] is None:
        return None
    _account_cache.update(value=value, key=hash(key), at=now)
    return value


def forget_account() -> None:
    """Al cambiar o borrar la clave, el saldo guardado ya no vale."""
    _account_cache.clear()


# ---------- La llamada


def _clean(text, key: str) -> str:
    """Un mensaje del servicio, corto y sin la clave (por si la repitiera)."""
    text = " ".join(str(text or "").split())[:160]
    return text.replace(key, "***") if key else text


def get(path: str, params: dict) -> dict | None:
    """GET a API.SH. Devuelve el JSON, o None si el servicio dice 404 (no existe: cobra igual). Lanza
    QuotaReached (tope), BlockedError (clave rechazada: no se insiste hoy) o ShopError (lo demás), siempre
    con el mensaje en claro y SIN la clave."""
    key = api_key()
    if not key:
        raise BlockedError(MISSING_KEY)
    with _lock:  # una llamada cada vez: el recuento de créditos no se pisa
        used, limit = credits()
        if used + 1 > limit:
            raise QuotaReached(quota_text(used, limit))
        query = {**params, "raw": 0}
        try:
            with httpx.Client(timeout=config.APISH_TIMEOUT_SECONDS, transport=transport) as client:
                response = client.get(config.APISH_BASE + path, params=query, headers={"x-api-key": key})
        except httpx.TimeoutException:
            raise ShopError(f"API.SH: tiempo agotado ({config.APISH_TIMEOUT_SECONDS:g} s)") from None
        except httpx.HTTPError as exc:
            raise ShopError(f"API.SH: no se pudo conectar ({type(exc).__name__})") from None
        status = response.status_code
        try:
            body = response.json()
        except ValueError:
            body = None
        body = body if isinstance(body, dict) else {}
        spent = body.get("credits_used")
        if not isinstance(spent, int) or isinstance(spent, bool):
            # Sin el dato: cobran los 200 y los 404 (según su documentación); lo demás no.
            spent = 1 if status in (200, 404) else 0
        _spend(spent)
    message = _clean(body.get("error"), key)
    detail = f": {message}" if message else ""
    if status == 200 and body:
        return body
    if status == 404:
        return None
    if status == 401:
        raise BlockedError(f"API.SH rechaza la clave (HTTP 401){detail}. Pega otra en Tiendas")
    if status == 403:
        raise BlockedError(f"API.SH no deja usar esta clave aquí (HTTP 403){detail}")
    if status == 402:
        raise QuotaReached(f"API.SH dice que no quedan créditos en la cuenta (HTTP 402){detail}")
    if status == 429:
        raise BlockedError(f"API.SH pide esperar (HTTP 429){detail}")
    if status in (502, 503):
        raise ShopError(f"API.SH no llega a Uniqlo ahora (HTTP {status}){detail}")
    raise ShopError(f"API.SH: HTTP {status}{detail}" if status != 200 else "API.SH: la respuesta no era la esperada")
