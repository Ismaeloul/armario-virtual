# Armario virtual

Armario personal: fotos de las prendas, análisis con IA y (más adelante) outfit diario.
Las decisiones de diseño y el plan de fases están en [CLAUDE.md](CLAUDE.md).

## Desarrollo en local

Backend (API en http://localhost:8000):

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # en Linux/Mac: .venv/bin/python
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

Frontend (http://localhost:5173, con la API redirigida al backend):

```bash
cd frontend
npm install
npm run dev
```

Tests del backend:

```bash
cd backend
.venv/Scripts/python -m pytest
```

Si existe `frontend/dist` (tras `npm run build`), el backend sirve también la app en el puerto 8000.

## Despliegue con Docker (Umbrel)

```bash
cp .env.example .env        # y pon tu ANTHROPIC_API_KEY
docker compose up -d --build
```

La app queda en `http://<ip-del-umbrel>:8765`. Todo lo persistente está en `data/`.

### Iniciar sesión en Codex (suscripción de ChatGPT)

Una sola vez, dentro del contenedor:

```bash
docker compose exec armario codex login --device-auth
```

Abre el enlace que muestra, inicia sesión y escribe el código. La sesión se guarda en `codex-home/`
y Codex la renueva sola. Hay que tener activado el inicio de sesión por código de dispositivo en los
ajustes de seguridad de ChatGPT.

Sin sesión de Codex la app sigue funcionando: usa Claude y lo indica en el borrador.

## Sin login

La app no tiene autenticación. Úsala solo en la red local o por Tailscale; no la expongas a internet.
