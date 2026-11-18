"""Fotos «de tienda» con Codex: de la foto hecha con el móvil a una de producto sobre fondo liso.

Codex no recorta la foto: la vuelve a dibujar con su herramienta de imágenes, así que puede cambiar
detalles. Por eso la original no se toca y el resultado se enseña antes de usarlo.

El CLI deja la imagen en `CODEX_HOME/generated_images/<sesión>/`; de ahí se lee y se borra.
"""
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from ... import config
from . import codex_models
from .base import AnalysisError
from .process import NEW_SESSION, kill_tree

TIMEOUT_SECONDS = int(os.environ.get("ARMARIO_STUDIO_TIMEOUT", "240"))

# Qué se ve en cada foto, según sea ropa o calzado (las mismas vistas que al añadir una prenda).
VIEWS = {
    "ropa": {"front": "la parte DELANTERA", "back": "la parte TRASERA (la espalda)", "extra": "otra vista"},
    "calzado": {"front": "un LATERAL", "back": "la vista DE FRENTE", "extra": "el OTRO LATERAL"},
}

_SESSION_RE = re.compile(r"session id:\s*([0-9a-f-]{20,})", re.I)


def build_prompt(view: str, kind: str, others: list[str], feedback: str | None = None,
                 has_previous: bool = False) -> str:
    """`view` es la foto que se edita (la primera adjunta); `others`, las vistas que van de referencia.
    `feedback` es lo que el usuario dice que salió mal en el intento anterior (la última foto, si va)."""
    names = VIEWS[kind]
    lines = [
        "Usa tu herramienta de generación de imágenes para editar la PRIMERA foto adjunta y dejarla como "
        "una foto de producto de una tienda online.",
        f"La primera foto enseña {names[view]} de la prenda. El resultado tiene que enseñar esa misma "
        "vista, no otra.",
    ]
    if others:
        listed = "; ".join(f"la {n}ª foto es {names[o]}" for n, o in enumerate(others, start=2))
        lines.append(
            f"Las demás fotos son la MISMA prenda vista desde otro lado, solo como referencia ({listed}). "
            "No las edites ni mezcles sus detalles con los de la primera."
        )
    if kind == "ropa":
        lines.append(
            "Es la misma prenda exacta: mismo color, mismo estampado, mismos textos y logos en el mismo "
            "sitio, mismas proporciones, mismos bolsillos, cremalleras, botones y costuras. Extendida y bien "
            "colocada, sin arrugas raras, con las mangas o las perneras estiradas."
        )
        lines.append(
            "Ojo con el cuello y la capucha: por delante se ve la abertura del cuello o de la capucha (y los "
            "cordones, si los tiene); por detrás la capucha cae cerrada sobre la espalda. Dibújalo según la "
            "vista que toca, no al revés."
        )
    else:
        lines.append(
            "Es el mismo calzado exacto: mismo modelo, mismos colores y materiales, mismos logos, misma suela "
            "y mismos cordones, visto desde el mismo lado y con la misma orientación."
        )
    lines.append(
        "Fondo liso gris muy claro, luz de estudio suave, sin mesa, sin suelo, sin manos, sin percha y sin "
        "ningún otro objeto. Imagen vertical 3:4 con la prenda centrada y entera. No inventes nada que no "
        "se vea en las fotos."
    )
    if feedback:
        lines.append(
            ("Ya lo intentaste una vez: la ÚLTIMA foto adjunta es tu intento anterior. " if has_previous
             else "Ya lo intentaste una vez. ")
            + "El dueño de la prenda dice que no quedó bien por esto: «" + feedback.strip() + "». "
            "Corrígelo fijándote en la primera foto, que es la que manda."
        )
    lines.append("Responde con una sola línea.")
    return "\n".join(lines)


def _images_dir() -> Path:
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    return home / "generated_images"


def _newest_image(folder: Path, since: float) -> Path | None:
    found = [
        p for p in folder.rglob("*")
        if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp") and p.stat().st_mtime >= since
    ]
    return max(found, key=lambda p: p.stat().st_mtime, default=None)


def product_photo(target: Path, view: str, kind: str, others: list[tuple[str, Path]],
                  feedback: str | None = None, previous: Path | None = None) -> bytes:
    """La foto `target` redibujada como foto de producto. `others` son (vista, foto) de referencia.
    Para rehacerla: `feedback` (qué salió mal) y `previous` (el intento anterior)."""
    binary = shutil.which(config.CODEX_BIN)
    if not binary:
        raise AnalysisError("Codex no está instalado en el servidor")

    started = time.time() - 2
    with tempfile.TemporaryDirectory(prefix="armario-estudio-") as tmp:
        cmd = [binary, "exec", "--ephemeral", "--skip-git-repo-check",
               "--sandbox", config.CODEX_SANDBOX, "--cd", tmp]
        cmd += codex_models.cli_args(codex_models.ANALYSIS)
        for image in (target, *(path for _, path in others), *([previous] if previous else [])):
            cmd += ["--image", str(image)]
        cmd.append("-")
        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", start_new_session=NEW_SESSION,
            )
        except OSError as exc:
            raise AnalysisError("No se pudo ejecutar Codex") from exc
        try:
            stdout, stderr = proc.communicate(
                build_prompt(view, kind, [name for name, _ in others], feedback, previous is not None),
                timeout=TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            kill_tree(proc)
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            raise AnalysisError("Codex tardó demasiado en editar la foto") from exc

    output = f"{stderr or ''}\n{stdout or ''}"
    if proc.returncode != 0:
        last = output.strip().splitlines()[-1:] or [""]
        text = last[0][:200]
        if "login" in text.lower() or "auth" in text.lower():
            raise AnalysisError("Codex no tiene sesión iniciada")
        raise AnalysisError(f"Codex terminó con error: {text}" if text else "Codex terminó con error")

    # La imagen de esta sesión; si el CLI no dijo cuál es, la más reciente desde que se lanzó.
    session = _SESSION_RE.search(output)
    folder = _images_dir() / session.group(1) if session else None
    image = _newest_image(folder, 0) if folder and folder.is_dir() else None
    if image is None and _images_dir().is_dir():
        image = _newest_image(_images_dir(), started)
    if image is None:
        raise AnalysisError("Codex no devolvió ninguna imagen")
    data = image.read_bytes()
    if image.parent != _images_dir():
        shutil.rmtree(image.parent, ignore_errors=True)  # no se acumulan en la carpeta de Codex
    else:
        image.unlink(missing_ok=True)
    return data
