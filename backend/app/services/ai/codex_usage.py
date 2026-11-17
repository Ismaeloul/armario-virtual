"""Cuánto límite de Codex queda en la cuenta con la que se ha iniciado sesión.

`codex exec` no lo devuelve, pero el propio CLI tiene un modo servidor (`codex app-server`)
que habla JSON por la entrada/salida estándar y sabe leerlo (`account/rateLimits/read`).
Aquí se arranca ese servidor, se le pregunta y se cierra.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time

from ... import config

_CACHE_SECONDS = 60
_cache: tuple[float, dict] | None = None
_lock = threading.Lock()


def _kill(process: subprocess.Popen) -> None:
    """El CLI es un lanzador que arranca otro proceso: hay que cerrar los dos."""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass


def _window(raw: dict | None) -> dict | None:
    if not raw:
        return None
    return {
        "used_percent": raw.get("usedPercent"),
        "window_minutes": raw.get("windowDurationMins"),
        "resets_at": raw.get("resetsAt"),  # segundos desde 1970
    }


def parse_rate_limits(result: dict) -> dict:
    """Se queda con lo que le importa a la app de la respuesta del CLI."""
    limits = result.get("rateLimits") or {}
    return {
        "plan": limits.get("planType"),
        "allowed": bool(result.get("ordinaryUsageAllowed", True)),
        "primary": _window(limits.get("primary")),  # ventana corta (5 horas)
        "secondary": _window(limits.get("secondary")),  # ventana larga (semanal)
    }


def read(timeout: float = 15) -> dict:
    """Devuelve los límites. Lanza RuntimeError si no se pueden leer."""
    global _cache
    with _lock:
        if _cache and time.time() - _cache[0] < _CACHE_SECONDS:
            return _cache[1]

        binary = shutil.which(config.CODEX_BIN)
        if not binary:
            raise RuntimeError("Codex no está instalado en el servidor")

        process = subprocess.Popen(
            [binary, "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=sys.platform != "win32",
        )
        answer: dict = {}
        done = threading.Event()

        def reader() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if message.get("id") == 2:
                    answer.update(message)
                    done.set()
                    return

        threading.Thread(target=reader, daemon=True).start()

        def send(message: dict) -> None:
            assert process.stdin is not None
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()

        try:
            send({"id": 1, "method": "initialize",
                  "params": {"clientInfo": {"name": "armario", "title": "Armario", "version": "1"}}})
            send({"method": "initialized"})
            send({"id": 2, "method": "account/rateLimits/read"})
            done.wait(timeout)
        except OSError as exc:
            raise RuntimeError("No se pudo hablar con Codex") from exc
        finally:
            _kill(process)

        if "result" not in answer:
            detail = (answer.get("error") or {}).get("message") if answer else None
            raise RuntimeError(detail or "Codex no devolvió los límites (¿sesión iniciada?)")

        data = parse_rate_limits(answer["result"])
        _cache = (time.time(), data)
        return data


def forget() -> None:
    """Tras iniciar o cerrar sesión, lo guardado ya no vale."""
    global _cache
    _cache = None
