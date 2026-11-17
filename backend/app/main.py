import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from sqlalchemy import select

from . import config
from .db import SessionLocal, init_db
from .models import Garment
from .routers import garments, settings, taste, today
from .services import storage


def _cleanup_orphan_photos() -> None:
    """Al arrancar: fuera las fotos de análisis que nunca se guardaron como prenda."""
    with SessionLocal() as db:
        referenced = {
            photo
            for row in db.execute(select(Garment.photo_front, Garment.photo_back, Garment.photo_extra, Garment.photo_label))
            for photo in row
            if photo
        }
    removed = storage.cleanup_orphans(referenced)
    if removed:
        logging.getLogger("armario").info("Fotos huérfanas borradas: %s", removed)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    config.ensure_dirs()
    init_db()
    _cleanup_orphan_photos()
    yield


app = FastAPI(title="Armario virtual", lifespan=lifespan)

if config.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(garments.router)
app.include_router(settings.router)
app.include_router(today.router)
app.include_router(taste.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


config.ensure_dirs()
app.mount("/media", StaticFiles(directory=config.PHOTOS_DIR), name="media")


# Un solo contenedor: si existe el build del frontend, FastAPI lo sirve también.
if config.FRONTEND_DIST.is_dir():
    assets = config.FRONTEND_DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith(("api/", "media/")):
            raise HTTPException(404)
        candidate = (config.FRONTEND_DIST / path).resolve()
        if path and candidate.is_file() and config.FRONTEND_DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(config.FRONTEND_DIST / "index.html")
