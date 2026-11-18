# Un solo contenedor: FastAPI sirve la API y el build del frontend.

# --- 1) Build del frontend ---
FROM node:22-alpine AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
RUN npm run build

# --- 2) Backend + CLI de Codex + Chromium ---
FROM python:3.12-slim
# PLAYWRIGHT_BROWSERS_PATH: el Chromium de Pull&Bear y Bershka, dentro de la imagen y en una ruta que el
# usuario 1000 puede leer (no en el HOME de root, que es donde Playwright lo pondría por defecto).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ARMARIO_DATA_DIR=/data \
    ARMARIO_FRONTEND_DIST=/app/frontend/dist \
    CODEX_HOME=/codex-home     HOME=/tmp \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

# Node solo hace falta para el lanzador del CLI de Codex (suscripción de ChatGPT).
# curl: JD Sports responde 403 a httpx y 200 a curl (backend/app/services/shops/fetch.py).
# xvfb: la pantalla virtual donde se abre Chromium CON ventana (Pull&Bear y Bershka no dejan pasar a
# un Chromium sin ventana). Se arranca solo mientras dura una consulta (services/shops/browser.py).
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm ca-certificates curl xvfb \
    && npm install -g @openai/codex --no-fund --no-audit \
    && apt-get clean && rm -rf /var/lib/apt/lists/* /root/.npm

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Chromium de Playwright (la revisión de la versión fijada en requirements.txt) y las librerías del
# sistema que necesita (`--with-deps` las instala con apt, por eso va como root y antes de COPY del
# código: así esta capa pesada se reutiliza mientras no cambie requirements.txt). Sin el «headless
# shell»: aquí solo se usa el Chromium con ventana. Si algo de esto faltara en el Umbrel, la app arranca
# igual y el panel Tiendas dice «No disponible» o «el navegador no arranca» con el motivo.
RUN python -m playwright install --with-deps --no-shell chromium \
    && chmod -R a+rX /opt/ms-playwright \
    && mkdir -p /tmp/.X11-unix && chmod 1777 /tmp/.X11-unix \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY backend/app backend/app
COPY --from=frontend /src/dist frontend/dist

# En Umbrel corre sin root (1000:1000): las carpetas de datos deben poder escribirse.
RUN mkdir -p /data /codex-home && chown 1000:1000 /data /codex-home
VOLUME ["/data", "/codex-home"]
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "8000"]
