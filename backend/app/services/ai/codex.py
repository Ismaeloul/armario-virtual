"""Codex con la suscripción de ChatGPT, a través del CLI en modo no interactivo.

No usa API key: reutiliza la sesión guardada en CODEX_HOME (auth.json). Codex es un agente
que puede ejecutar comandos, así que se lanza en una carpeta temporal vacía, en solo lectura
y sin guardar la sesión.
"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from ... import config
from .base import OUTPUT_SCHEMA, PROMPT, AnalysisError


class CodexAnalyzer:
    name = "codex"

    def _binary(self) -> str | None:
        return shutil.which(config.CODEX_BIN)

    def available(self) -> bool:
        return self._binary() is not None

    def analyze(self, images: list[Path]) -> str:
        binary = self._binary()
        if not binary:
            raise AnalysisError("Codex no está instalado en el servidor")

        with tempfile.TemporaryDirectory(prefix="armario-codex-") as tmp:
            work = Path(tmp)
            schema_file = work / "esquema.json"
            result_file = work / "resultado.json"
            schema_file.write_text(json.dumps(OUTPUT_SCHEMA), encoding="utf-8")

            cmd = [
                binary, "exec",
                "--ephemeral",
                "--skip-git-repo-check",
                "--sandbox", "read-only",
                "--cd", str(work),
                "--output-schema", str(schema_file),
                "--output-last-message", str(result_file),
            ]
            if config.CODEX_MODEL:
                cmd += ["--model", config.CODEX_MODEL]
            for image in images:
                cmd += ["--image", str(image)]
            cmd.append("-")  # el prompt entra por stdin: sin problemas de comillas

            try:
                proc = subprocess.run(
                    cmd,
                    input=PROMPT,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=config.AI_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired as exc:
                raise AnalysisError("Codex tardó demasiado en responder") from exc
            except OSError as exc:
                raise AnalysisError("No se pudo ejecutar Codex") from exc

            if proc.returncode != 0:
                detalle = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or [""]
                texto = detalle[0][:200]
                if "login" in texto.lower() or "auth" in texto.lower():
                    raise AnalysisError("Codex no tiene sesión iniciada")
                raise AnalysisError(f"Codex terminó con error: {texto}" if texto else "Codex terminó con error")

            if result_file.is_file():
                return result_file.read_text(encoding="utf-8")
            if proc.stdout.strip():
                return proc.stdout
            raise AnalysisError("Codex no devolvió contenido")
