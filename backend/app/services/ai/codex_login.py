"""Inicio y cierre de sesión de Codex desde la app.

Usa el inicio por código de dispositivo del CLI (`codex login --device-auth`): el CLI imprime
un enlace y un código de un solo uso y se queda esperando a que el usuario lo introduzca en
su navegador. Aquí se lanza ese proceso en segundo plano, se leen el enlace y el código de
su salida y se informa del estado para que Ajustes lo muestre.
"""
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field

from ... import config

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_URL = re.compile(r"https://\S+")
_CODE = re.compile(r"\b[A-Z0-9]{4}-[A-Z0-9]{4,6}\b")

LOGIN_TIMEOUT_SECONDS = 15 * 60  # lo que dura el código


def parse_device_prompt(text: str) -> tuple[str | None, str | None]:
    """Saca el enlace y el código de lo que imprime el CLI."""
    clean = _ANSI.sub("", text)
    url = _URL.search(clean)
    code = _CODE.search(clean)
    return (url.group(0) if url else None, code.group(0) if code else None)


@dataclass
class _Attempt:
    process: subprocess.Popen
    started: float = field(default_factory=time.time)
    output: str = ""
    url: str | None = None
    code: str | None = None


_lock = threading.Lock()
_attempt: _Attempt | None = None
_last_error: str | None = None


def _read_output(attempt: _Attempt) -> None:
    assert attempt.process.stdout is not None
    for line in attempt.process.stdout:
        attempt.output += line
        if not (attempt.url and attempt.code):
            attempt.url, attempt.code = parse_device_prompt(attempt.output)


def _expire(attempt: _Attempt) -> None:
    """Si nadie introduce el código, el proceso no se queda colgado para siempre."""
    try:
        attempt.process.wait(timeout=LOGIN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        attempt.process.terminate()


def start() -> dict:
    """Empieza un inicio de sesión (o devuelve el que ya está en curso)."""
    global _attempt, _last_error
    binary = shutil.which(config.CODEX_BIN)
    if not binary:
        raise RuntimeError("Codex no está instalado en el servidor")

    with _lock:
        if _attempt is None or _attempt.process.poll() is not None:
            _last_error = None
            process = subprocess.Popen(
                [binary, "login", "--device-auth"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            _attempt = _Attempt(process=process)
            threading.Thread(target=_read_output, args=(_attempt,), daemon=True).start()
            threading.Thread(target=_expire, args=(_attempt,), daemon=True).start()
        attempt = _attempt

    # El CLI tarda un momento en pedir el código a OpenAI.
    deadline = time.time() + 20
    while time.time() < deadline and not (attempt.url and attempt.code):
        if attempt.process.poll() is not None:
            break
        time.sleep(0.2)

    if not (attempt.url and attempt.code):
        attempt.process.terminate()
        _last_error = _last_line(attempt.output) or "Codex no devolvió un código"
        raise RuntimeError(_last_error)
    return status()


def _last_line(output: str) -> str:
    lines = [line.strip() for line in _ANSI.sub("", output).splitlines() if line.strip()]
    return lines[-1][:200] if lines else ""


def status() -> dict:
    """Estado del inicio de sesión en curso: idle, pending, done o failed."""
    global _last_error
    attempt = _attempt
    if attempt is None:
        return {"state": "idle", "url": None, "code": None, "error": _last_error}

    exit_code = attempt.process.poll()
    if exit_code is None:
        remaining = max(0, int(LOGIN_TIMEOUT_SECONDS - (time.time() - attempt.started)))
        return {"state": "pending", "url": attempt.url, "code": attempt.code, "error": None, "expires_in": remaining}
    if exit_code == 0:
        return {"state": "done", "url": None, "code": None, "error": None}
    _last_error = _last_line(attempt.output) or "El inicio de sesión no se completó"
    return {"state": "failed", "url": None, "code": None, "error": _last_error}


def cancel() -> None:
    global _attempt
    with _lock:
        if _attempt is not None and _attempt.process.poll() is None:
            _attempt.process.terminate()
        _attempt = None


def logout() -> None:
    """Cierra la sesión guardada (borra las credenciales de CODEX_HOME)."""
    binary = shutil.which(config.CODEX_BIN)
    if not binary:
        raise RuntimeError("Codex no está instalado en el servidor")
    cancel()
    try:
        subprocess.run([binary, "logout"], capture_output=True, text=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise RuntimeError("No se pudo cerrar la sesión de Codex") from exc
