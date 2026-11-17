from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import catalog
from ..db import get_db
from ..models import Garment, WearLog, now_utc
from ..schemas import (
    AnalyzeResponse,
    Color,
    CorrectionsReport,
    GarmentCreate,
    GarmentOut,
    GarmentUpdate,
    Photo,
    Summary,
    WearIn,
)
from ..services import ai, storage
from ..services.ai.base import build_prompt
from .settings import read_settings

router = APIRouter(prefix="/api", tags=["prendas"])


def _wear_stats(db: Session, ids: list[int]) -> dict[int, tuple[int, date | None]]:
    if not ids:
        return {}
    rows = db.execute(
        select(WearLog.garment_id, func.count(WearLog.id), func.max(WearLog.worn_on))
        .where(WearLog.garment_id.in_(ids))
        .group_by(WearLog.garment_id)
    ).all()
    return {gid: (count, last) for gid, count, last in rows}


def _to_out(g: Garment, stats: dict[int, tuple[int, date | None]]) -> GarmentOut:
    count, last = stats.get(g.id, (0, None))
    return GarmentOut(
        id=g.id,
        name=g.name,
        type=g.type,
        category=g.category,
        color_primary=Color(name=g.color_primary, hex=g.color_primary_hex),
        colors_secondary=[Color(**c) for c in (g.colors_secondary or [])],
        pattern=g.pattern,
        style=g.style,
        details=g.details,
        season=g.season,
        brand=g.brand,
        size=g.size,
        notes=g.notes,
        photo_front=storage.to_schema(g.photo_front),
        photo_back=storage.to_schema(g.photo_back) if g.photo_back else None,
        photo_label=storage.to_schema(g.photo_label) if g.photo_label else None,
        in_laundry=g.in_laundry,
        laundry_since=g.laundry_since,
        favorite=g.favorite,
        ai_provider=g.ai_provider,
        ai_confidence=g.ai_confidence,
        wear_count=count,
        last_worn_on=last,
        created_at=g.created_at,
        updated_at=g.updated_at,
    )


def _get_or_404(db: Session, garment_id: int) -> Garment:
    garment = db.get(Garment, garment_id)
    if not garment:
        raise HTTPException(404, "Prenda no encontrada")
    return garment


def _resolve_photo(upload: UploadFile | None, existing_id: str | None, required: bool) -> str | None:
    """Una foto llega como archivo nuevo o como id de una ya subida (para reintentar)."""
    try:
        if upload is not None and upload.filename:
            return storage.save_upload(upload.file.read(), upload.filename)
        if existing_id:
            if not storage.exists(existing_id):
                raise HTTPException(404, "La foto ya no existe; vuelve a subirla")
            return existing_id
    except storage.InvalidPhoto as exc:
        raise HTTPException(422, str(exc)) from exc
    if required:
        raise HTTPException(422, "Falta la foto delantera")
    return None


@router.post("/garments/analyze", response_model=AnalyzeResponse)
def analyze_garment(
    front: UploadFile | None = File(None),
    back: UploadFile | None = File(None),
    label: UploadFile | None = File(None),
    front_id: str | None = Form(None),
    back_id: str | None = Form(None),
    label_id: str | None = Form(None),
    skip_ai: bool = Form(False),
    db: Session = Depends(get_db),
):
    """Guarda las fotos y devuelve un borrador. No crea la prenda.

    Si la IA falla, responde igualmente con las fotos y `draft: null` para que la app
    ofrezca reintentar (mismos ids) o rellenar a mano.
    """
    front_photo = _resolve_photo(front, front_id, required=True)
    back_photo = _resolve_photo(back, back_id, required=False)
    label_photo = _resolve_photo(label, label_id, required=False)

    if skip_ai:
        result = ai.AnalysisResult(draft=None, provider=None, fallback_used=False, error=None)
    else:
        # La trasera también se manda: algunas prendas tienen el diseño detrás.
        images = [storage.photo_path(front_photo)]
        if back_photo:
            images.append(storage.photo_path(back_photo))
        if label_photo:  # la etiqueta, para leer marca y talla
            images.append(storage.photo_path(label_photo))
        result = ai.analyze(
            images,
            preferred=read_settings(db).ai_provider,
            prompt=build_prompt(has_back=bool(back_photo), has_label=bool(label_photo)),
        )

    return AnalyzeResponse(
        photo_front=storage.to_schema(front_photo),
        photo_back=storage.to_schema(back_photo) if back_photo else None,
        photo_label=storage.to_schema(label_photo) if label_photo else None,
        draft=result.draft,
        provider=result.provider,
        fallback_used=result.fallback_used,
        error=result.error,
    )


@router.post("/garments", response_model=GarmentOut, status_code=201)
def create_garment(body: GarmentCreate, db: Session = Depends(get_db)):
    for photo_id in (body.photo_front, body.photo_back, body.photo_label):
        if photo_id and not storage.exists(photo_id):
            raise HTTPException(422, "La foto no existe; vuelve a subirla")

    garment = Garment(
        name=body.name.strip(),
        type=body.type,
        category=catalog.category_of(body.type),
        color_primary=body.color_primary.name,
        color_primary_hex=body.color_primary.hex.lower(),
        colors_secondary=[c.model_dump() for c in body.colors_secondary],
        pattern=body.pattern,
        style=body.style,
        details=body.details.strip(),
        season=body.season,
        brand=body.brand,
        size=body.size,
        notes=body.notes.strip(),
        photo_front=body.photo_front,
        photo_back=body.photo_back,
        photo_front_original=storage.original_name(body.photo_front),
        photo_back_original=storage.original_name(body.photo_back) if body.photo_back else None,
        photo_label=body.photo_label,
        photo_label_original=storage.original_name(body.photo_label) if body.photo_label else None,
        ai_provider=body.ai_provider,
        ai_confidence=body.ai_confidence,
        ai_draft=body.ai_draft.model_dump() if body.ai_draft else None,
    )
    db.add(garment)
    db.commit()
    return _to_out(garment, {})


@router.get("/garments", response_model=list[GarmentOut])
def list_garments(
    season: str | None = Query(None),
    type: str | None = Query(None),
    category: str | None = Query(None),
    in_laundry: bool | None = Query(None),
    q: str | None = Query(None, max_length=80),
    db: Session = Depends(get_db),
):
    stmt = select(Garment).order_by(Garment.created_at.desc(), Garment.id.desc())
    if season:
        stmt = stmt.where(Garment.season == season)
    if type:
        stmt = stmt.where(Garment.type == type)
    if category:
        stmt = stmt.where(Garment.category == category)
    if in_laundry is not None:
        stmt = stmt.where(Garment.in_laundry == in_laundry)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Garment.name.ilike(like), Garment.brand.ilike(like), Garment.type.ilike(like)))
    garments = list(db.scalars(stmt))
    stats = _wear_stats(db, [g.id for g in garments])
    return [_to_out(g, stats) for g in garments]


@router.get("/garments/summary", response_model=Summary)
def garments_summary(db: Session = Depends(get_db)):
    by_type = dict(db.execute(select(Garment.type, func.count()).group_by(Garment.type)).all())
    by_category = dict(db.execute(select(Garment.category, func.count()).group_by(Garment.category)).all())
    in_laundry = db.scalar(select(func.count()).select_from(Garment).where(Garment.in_laundry.is_(True)))
    return Summary(total=sum(by_type.values()), in_laundry=in_laundry or 0, by_type=by_type, by_category=by_category)


_COMPARED = ["name", "type", "color_primary", "colors_secondary", "pattern", "style", "season", "brand", "size"]


def _saved_value(garment: Garment, field: str):
    if field == "color_primary":
        return garment.color_primary
    if field == "colors_secondary":
        return sorted(c["name"] for c in garment.colors_secondary or [])
    return getattr(garment, field)


def _draft_value(draft: dict, field: str):
    if field == "color_primary":
        return draft["color_primary"]["name"]
    if field == "colors_secondary":
        return sorted(c["name"] for c in draft.get("colors_secondary") or [])
    return draft.get(field)


@router.get("/ai/corrections", response_model=CorrectionsReport)
def ai_corrections(db: Session = Depends(get_db)):
    """Qué cambió el usuario respecto a lo que propuso la IA. Sirve para afinar las instrucciones.

    Solo compara nombres de la paleta, no el tono exacto, y no cuenta detalles ni notas.
    """
    garments = [g for g in db.scalars(select(Garment).order_by(Garment.id)) if g.ai_draft]
    corrections, by_field, untouched = [], {}, 0
    for g in garments:
        changed = False
        for field in _COMPARED:
            ai_value, saved = _draft_value(g.ai_draft, field), _saved_value(g, field)
            if ai_value != saved:
                changed = True
                by_field[field] = by_field.get(field, 0) + 1
                corrections.append(
                    dict(garment_id=g.id, garment=g.name, provider=g.ai_provider, field=field,
                         ai=ai_value, saved=saved, photo=storage.to_schema(g.photo_front).thumb_url)
                )
        untouched += not changed
    return CorrectionsReport(analyzed=len(garments), untouched=untouched, by_field=by_field, corrections=corrections)


@router.get("/garments/{garment_id}", response_model=GarmentOut)
def get_garment(garment_id: int, db: Session = Depends(get_db)):
    garment = _get_or_404(db, garment_id)
    return _to_out(garment, _wear_stats(db, [garment.id]))


@router.patch("/garments/{garment_id}", response_model=GarmentOut)
def update_garment(garment_id: int, body: GarmentUpdate, db: Session = Depends(get_db)):
    garment = _get_or_404(db, garment_id)
    changes = body.model_dump(exclude_unset=True)

    if "color_primary" in changes and body.color_primary:
        garment.color_primary = body.color_primary.name
        garment.color_primary_hex = body.color_primary.hex.lower()
        changes.pop("color_primary")
    if "type" in changes and body.type:
        garment.category = catalog.category_of(body.type)
    if "in_laundry" in changes and body.in_laundry is not None:
        garment.laundry_since = now_utc() if body.in_laundry else None

    not_nullable = {"name", "type", "pattern", "style", "season", "details", "notes",
                    "colors_secondary", "favorite", "in_laundry"}
    for key, value in changes.items():
        if value is None and key in not_nullable:
            continue
        setattr(garment, key, value)

    db.commit()
    return _to_out(garment, _wear_stats(db, [garment.id]))


@router.delete("/garments/{garment_id}", status_code=204)
def delete_garment(garment_id: int, db: Session = Depends(get_db)):
    garment = _get_or_404(db, garment_id)
    photos = (garment.photo_front, garment.photo_back, garment.photo_label)
    db.delete(garment)
    db.commit()
    for photo_id in photos:
        storage.delete(photo_id)


@router.post("/garments/{garment_id}/wear", response_model=GarmentOut)
def wear_garment(garment_id: int, body: WearIn | None = None, db: Session = Depends(get_db)):
    """Registra un uso (lo usará la Fase 2 para no repetir outfits)."""
    garment = _get_or_404(db, garment_id)
    db.add(WearLog(garment_id=garment.id, worn_on=(body.worn_on if body and body.worn_on else date.today())))
    db.commit()
    return _to_out(garment, _wear_stats(db, [garment.id]))


@router.post("/photos/{photo_id}/rotate", response_model=Photo)
def rotate_photo(photo_id: str, db: Session = Depends(get_db)):
    """Gira una foto 90° a la derecha, esté ya en una prenda o todavía en un borrador."""
    try:
        new_id = storage.rotate(photo_id)
    except storage.InvalidPhoto as exc:
        raise HTTPException(404, str(exc)) from exc

    for garment in db.scalars(
        select(Garment).where(
            or_(Garment.photo_front == photo_id, Garment.photo_back == photo_id, Garment.photo_label == photo_id)
        )
    ):
        if garment.photo_label == photo_id:
            garment.photo_label = new_id
            garment.photo_label_original = storage.original_name(new_id)
        if garment.photo_front == photo_id:
            garment.photo_front = new_id
            garment.photo_front_original = storage.original_name(new_id)
        if garment.photo_back == photo_id:
            garment.photo_back = new_id
            garment.photo_back_original = storage.original_name(new_id)
    db.commit()
    return storage.to_schema(new_id)


@router.post("/laundry/clear")
def clear_laundry(db: Session = Depends(get_db)):
    """«Marcar todas como limpias»."""
    garments = list(db.scalars(select(Garment).where(Garment.in_laundry.is_(True))))
    for garment in garments:
        garment.in_laundry = False
        garment.laundry_since = None
    db.commit()
    return {"cleared": len(garments)}
