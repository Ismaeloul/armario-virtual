"""Utilidades para lanzar el CLI de Codex como proceso hijo."""
import os
import signal
import subprocess
import sys

# En Linux/macOS el CLI se lanza en su propia sesión para poder matar el grupo entero.
NEW_SESSION = sys.platform != "win32"


def kill_tree(process: subprocess.Popen) -> None:
    """El CLI es un lanzador que arranca otro proceso: hay que cerrar los dos."""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
