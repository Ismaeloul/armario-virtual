# Un solo contenedor: FastAPI sirve la API y el build del frontend.

# --- 1) Build del frontend ---
FROM node:22-alpine AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
RUN npm run build

# --- 2) Backend + CLI de Codex ---
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ARMARIO_DATA_DIR=/data \
    ARMARIO_FRONTEND_DIST=/app/frontend/dist \
    CODEX_HOME=/codex-home     HOME=/tmp

# Node solo hace falta para el lanzador del CLI de Codex (suscripción de ChatGPT).
# curl: JD Sports responde 403 a httpx y 200 a curl (backend/app/services/shops/fetch.py).
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm ca-certificates curl \
    && npm install -g @openai/codex --no-fund --no-audit \
    && apt-get clean && rm -rf /var/lib/apt/lists/* /root/.npm

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/app backend/app
COPY --from=frontend /src/dist frontend/dist

# En Umbrel corre sin root (1000:1000): las carpetas de datos deben poder escribirse.
RUN mkdir -p /data /codex-home && chown 1000:1000 /data /codex-home
VOLUME ["/data", "/codex-home"]
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "8000"]
