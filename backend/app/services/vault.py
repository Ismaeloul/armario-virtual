"""Claves de servicios de pago guardadas CIFRADAS (de momento, solo la de API.SH para Uniqlo).

Petición expresa del usuario: la clave se pega una vez y nadie puede volver a verla. Por eso:

- En la base de datos (`settings`, en `data/`) solo se guarda el texto cifrado con Fernet (AES-128 en modo
  CBC con HMAC-SHA256). Ninguna respuesta de la API la devuelve: solo se dice si hay una guardada.
- La clave maestra que la descifra se genera la primera vez y va en un archivo APARTE, fuera de `data/`
  (permisos 600): en la carpeta de Codex (`CODEX_HOME`; en el Umbrel es el volumen `/codex-home`, distinto de
  `/data`). Así una copia de `data/` sola no basta para sacar la clave. Si no hay `CODEX_HOME`, en
  `~/.armario-virtual/`. `ARMARIO_SECRETS_DIR` manda sobre las dos (los tests lo usan).
- Si la clave maestra se pierde (otro equipo, volumen borrado), lo guardado ya no se puede descifrar: se
  trata como si no hubiera clave («Falta la clave de API») y se pega otra. No rompe nada.
- Desarrollo local: la variable de entorno `ARMARIO_APISH_KEY`, si está, tiene prioridad sobre la guardada
  (no se guarda ni se cifra: es del entorno de quien la pone).

Lo que NO protege: quien entre en el equipo con acceso a los dos volúmenes (o al proceso en marcha) puede
descifrarla; y la app no tiene login (solo red local y Tailscale), así que cualquiera de esa red puede
CAMBIAR o BORRAR la clave, aunque no leerla.

Nada de aquí escribe la clave en un log, en un mensaje de error ni en una excepción.
"""
import json
import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from ..models import Setting

log = logging.getLogger(__name__)

MASTER_FILE = "armario-vault.key"
ENV_KEYS = {"apish": "ARMARIO_APISH_KEY"}
_PREFIX = "secret_"  # `settings`: secret_apish = el texto cifrado
MIN_LENGTH, MAX_LENGTH = 8, 300


class BadSecret(ValueError):
    """Lo pegado no tiene forma de clave. El mensaje NO lleva la clave."""


def secrets_dir() -> Path:
    """La carpeta de la clave maestra: fuera de `data/` (ver arriba)."""
    own = os.environ.get("ARMARIO_SECRETS_DIR")
    if own:
        return Path(own)
    codex = os.environ.get("CODEX_HOME")
    if codex:
        return Path(codex)
    return Path.home() / ".armario-virtual"


def _master_path() -> Path:
    return secrets_dir() / MASTER_FILE


def _read_master() -> bytes | None:
    try:
        data = _master_path().read_bytes().strip()
    except OSError:
        return None
    return data or None


def _create_master() -> bytes:
    """La clave maestra, creándola si no existe (solo al guardar una clave: leer nunca la crea)."""
    found = _read_master()
    if found:
        return found
    folder = secrets_dir()
    folder.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    path = _master_path()
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:  # otro hilo la acaba de crear
        return _read_master() or key
    with os.fdopen(fd, "wb") as handle:
        handle.write(key)
    try:
        os.chmod(path, 0o600)  # por si el umask la dejó más abierta (en Windows apenas tiene efecto)
    except OSError:
        pass
    return key


def _clean(value: str) -> str:
    text = (value or "").strip()
    if not MIN_LENGTH <= len(text) <= MAX_LENGTH or any(ch.isspace() for ch in text) or not text.isprintable():
        raise BadSecret("Eso no parece una clave de API: pégala entera, sin espacios")
    return text


def save(db: Session, name: str, value: str) -> None:
    """Guarda la clave `name` cifrada (sustituye la que hubiera)."""
    token = Fernet(_create_master()).encrypt(_clean(value).encode()).decode()
    db.merge(Setting(key=_PREFIX + name, value=json.dumps(token)))
    db.commit()


def delete(db: Session, name: str) -> None:
    row = db.get(Setting, _PREFIX + name)
    if row is not None:
        db.delete(row)
        db.commit()


def stored(db: Session, name: str) -> bool:
    """¿Hay una clave guardada (y se puede descifrar con la clave maestra de este equipo)?"""
    return _decrypt(db, name) is not None


def get(db: Session, name: str) -> str | None:
    """La clave en claro, para mandarla al servicio y NADA más. La del entorno manda. None si no hay o no
    se puede descifrar."""
    env = ENV_KEYS.get(name)
    if env and os.environ.get(env, "").strip():
        return os.environ[env].strip()
    return _decrypt(db, name)


def from_env(name: str) -> bool:
    env = ENV_KEYS.get(name)
    return bool(env and os.environ.get(env, "").strip())


def _decrypt(db: Session, name: str) -> str | None:
    row = db.get(Setting, _PREFIX + name)
    if row is None:
        return None
    try:
        token = json.loads(row.value)
    except ValueError:
        return None
    master = _read_master()
    if not master or not isinstance(token, str):
        log.warning("Clave de %s guardada, pero falta la clave maestra para descifrarla", name)
        return None
    try:
        return Fernet(master).decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        log.warning("La clave de %s guardada no se puede descifrar con la clave maestra de este equipo", name)
        return None
