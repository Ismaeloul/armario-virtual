"""Fotos de prendas en disco.

Cada foto tiene un id (uuid hex). Se guardan tres archivos:
  photos/<id>.webp        versión de trabajo (~1600 px)
  photos/<id>_thumb.webp  miniatura para el catálogo
  originals/<id><ext>     el archivo tal como se subió
"""
import io
import re
import time
import uuid
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .. import config
from ..schemas import Photo

try:  # fotos HEIC del iPhone
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # pragma: no cover
    pass

_ID_RE = re.compile(r"^[0-9a-f]{32}$")
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class InvalidPhoto(ValueError):
    pass


def _check_id(photo_id: str) -> str:
    if not _ID_RE.match(photo_id):
        raise InvalidPhoto("Identificador de foto no válido")
    return photo_id


def photo_path(photo_id: str) -> Path:
    return config.PHOTOS_DIR / f"{_check_id(photo_id)}.webp"


def thumb_path(photo_id: str) -> Path:
    return config.PHOTOS_DIR / f"{_check_id(photo_id)}_thumb.webp"


def exists(photo_id: str) -> bool:
    return photo_path(photo_id).is_file()


def original_name(photo_id: str) -> str | None:
    matches = list(config.ORIGINALS_DIR.glob(f"{_check_id(photo_id)}.*"))
    return matches[0].name if matches else None


def to_schema(photo_id: str) -> Photo:
    return Photo(
        id=photo_id,
        url=f"/media/{photo_id}.webp",
        thumb_url=f"/media/{photo_id}_thumb.webp",
    )


def save_upload(data: bytes, filename: str | None) -> str:
    """Guarda original + versión de trabajo + miniatura. Devuelve el id de la foto."""
    if not data:
        raise InvalidPhoto("La foto está vacía")
    if len(data) > MAX_UPLOAD_BYTES:
        raise InvalidPhoto("La foto pesa demasiado (máximo 25 MB)")
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)  # respeta la orientación del móvil
        img = img.convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidPhoto("El archivo no es una imagen válida") from exc

    config.ensure_dirs()
    photo_id = uuid.uuid4().hex

    ext = Path(filename or "").suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,5}", ext):
        ext = ".bin"
    (config.ORIGINALS_DIR / f"{photo_id}{ext}").write_bytes(data)

    work = img.copy()
    work.thumbnail((config.PHOTO_MAX_SIDE, config.PHOTO_MAX_SIDE))
    work.save(photo_path(photo_id), "WEBP", quality=85)

    thumb = img.copy()
    thumb.thumbnail((config.THUMB_MAX_SIDE, config.THUMB_MAX_SIDE))
    thumb.save(thumb_path(photo_id), "WEBP", quality=80)

    return photo_id


def cleanup_orphans(referenced: set[str], max_age_hours: float = 24) -> int:
    """Borra las fotos que no pertenecen a ninguna prenda (análisis que no se llegaron a guardar).

    Solo las de hace más de `max_age_hours`, para no tocar un borrador que se está rellenando ahora.
    """
    limit = time.time() - max_age_hours * 3600
    removed = 0
    for path in config.PHOTOS_DIR.glob("*.webp"):
        photo_id = path.stem
        if not _ID_RE.match(photo_id):  # las miniaturas (<id>_thumb) se borran con su foto
            continue
        if photo_id in referenced or path.stat().st_mtime > limit:
            continue
        delete(photo_id)
        removed += 1
    return removed


def delete(photo_id: str | None) -> None:
    if not photo_id:
        return
    for p in (photo_path(photo_id), thumb_path(photo_id), *config.ORIGINALS_DIR.glob(f"{photo_id}.*")):
        p.unlink(missing_ok=True)
