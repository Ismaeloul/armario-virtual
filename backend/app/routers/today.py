"""Outfit del día: tiempo de la ciudad + propuesta entre las prendas disponibles."""
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import catalog
from ..db import get_db
from ..models import Garment, Outfit, Rating, WearLog
from ..schemas import GarmentOut
from ..services import outfits, weather
from .garments import _to_out, _wear_stats
from .settings import read_settings
from .taste import load_taste

router = APIRouter(prefix="/api", tags=["hoy"])

PROPOSED, CHOSEN, DISCARDED, REPLACED = "propuesto", "elegido", "descartado", "sustituido"

# Cuántos días atrás no se repite una combinación: la que se eligió («Me gusta») y la que solo se propuso.
CHOSEN_MEMORY_DAYS, PROPOSED_MEMORY_DAYS = 7, 2


class WeatherOut(BaseModel):
    city: str
    temp_now: float
    temp_max: float
    temp_min: float
    rain_probability: int
    description: str
    icon: str


class OutfitOut(BaseModel):
    id: int
    status: str
    affinity: int
    day_kind: str
    garments: list[GarmentOut]


class TodayOut(BaseModel):
    date: date
    city: str
    weather: WeatherOut | None
    outfit: OutfitOut | None
    missing: list[str]  # categorías imprescindibles sin prendas disponibles
    notes: list[str]  # avisos: "sin_capa", "sin_calzado", "sin_mas_combinaciones"
    in_laundry: int
    total: int


class NextIn(BaseModel):
    action: Literal["otra", "pasar"]


def _items(db: Session, garments: list[Garment], today: date) -> list[outfits.Item]:
    stats = _wear_stats(db, [g.id for g in garments])
    return [
        outfits.Item(
            id=g.id,
            type=g.type,
            category=g.category,
            color=g.color_primary,
            style=g.style,
            season=g.season,
            favorite=g.favorite,
            pattern=g.pattern,
            details=f"{g.name} {g.details or ''}",
            closure=g.closure,
            fit=g.fit,
            thickness=g.thickness,
            hood=g.hood,
            days_since_worn=(today - stats[g.id][1]).days if g.id in stats and stats[g.id][1] else None,
        )
        for g in garments
    ]


def _current(db: Session, today: date) -> Outfit | None:
    """El outfit vigente de hoy: el elegido si lo hay; si no, la última propuesta."""
    rows = list(
        db.scalars(
            select(Outfit).where(Outfit.day == today, Outfit.status.in_([CHOSEN, PROPOSED])).order_by(Outfit.id.desc())
        )
    )
    chosen = [o for o in rows if o.status == CHOSEN]
    return (chosen or rows or [None])[0]


def _still_valid(db: Session, outfit: Outfit) -> bool:
    """Una propuesta deja de valer si alguna prenda se borró o se metió en la lavadora."""
    garments = list(db.scalars(select(Garment).where(Garment.id.in_(outfit.garment_ids))))
    return len(garments) == len(outfit.garment_ids) and not any(g.in_laundry for g in garments)


def _generate(
    db: Session, today: date, forecast: weather.Weather | None, replaced: Outfit | None = None
) -> tuple[Outfit | None, list[str], list[str]]:
    """Propone y guarda un outfit. `replaced` es la propuesta que el usuario acaba de pedir cambiar."""
    available = list(db.scalars(select(Garment).where(Garment.in_laundry.is_(False))))
    categories = {g.category for g in available}
    missing = [c for c in ("parte_superior", "parte_inferior") if c not in categories]
    if missing:
        return None, [catalog.CATEGORIES[c] for c in missing], []

    recent = db.scalars(
        select(Outfit).where(Outfit.day >= today - timedelta(days=CHOSEN_MEMORY_DAYS)).order_by(Outfit.id)
    )
    # No repetir lo que se eligió estos días ni lo que ya se propuso hoy o hace nada, se eligiera o no:
    # así la primera propuesta de cada día cambia. Un «Pasar» no necesita más castigo aquí: ya queda
    # apuntado como valoración y lo tiene en cuenta lo aprendido (load_taste).
    shown_since = today - timedelta(days=PROPOSED_MEMORY_DAYS)
    avoid = [set(o.garment_ids) for o in recent if o.day >= shown_since or o.status == CHOSEN]

    proposal = outfits.propose(
        _items(db, available, today),
        temp_max=forecast.temp_max if forecast else None,
        rain_probability=forecast.rain_probability if forecast else 0,
        today=today,
        avoid=avoid,
        taste=load_taste(db),
    )
    if proposal is None:
        return None, [], []
    # Que no queden más combinaciones solo se avisa a quien acaba de pedir otra.
    notes = proposal.notes if replaced is not None else []
    if replaced is not None and set(proposal.ids) == set(replaced.garment_ids):
        # No hay nada distinto que ofrecer: se queda la misma propuesta en vez de guardar una copia.
        replaced.status = PROPOSED
        replaced.affinity = proposal.affinity
        db.commit()
        return replaced, [], notes
    outfit = Outfit(
        day=today,
        garment_ids=proposal.ids,
        status=PROPOSED,
        affinity=proposal.affinity,
        day_kind=proposal.day_kind,
        weather=forecast.as_dict() if forecast else None,
    )
    db.add(outfit)
    db.commit()
    return outfit, [], notes


def _response(db: Session, today: date, forecast, city: str, outfit: Outfit | None, missing, notes) -> TodayOut:
    garments_out: list[GarmentOut] = []
    if outfit:
        garments = {g.id: g for g in db.scalars(select(Garment).where(Garment.id.in_(outfit.garment_ids)))}
        stats = _wear_stats(db, list(garments))
        # Mismo orden en que se pensó: capa, arriba, abajo, calzado.
        garments_out = [_to_out(garments[i], stats) for i in outfit.garment_ids if i in garments]
        # Los avisos se calculan siempre, también al recargar una propuesta ya guardada. El de que no
        # quedan más combinaciones solo tiene sentido justo después de pedir otra.
        categories = {g.category for g in garments.values()}
        notes = [n for n in notes if n == "sin_mas_combinaciones"]
        if "calzado" not in categories:
            notes.append("sin_calzado")
        has_layer = db.scalar(
            select(func.count()).select_from(Garment).where(
                Garment.category == "capa_exterior", Garment.in_laundry.is_(False)
            )
        )
        if "capa_exterior" not in categories and not has_layer and outfits.wants_layer(
            outfit.day_kind, forecast.temp_max if forecast else None, forecast.rain_probability if forecast else 0
        ):
            notes.append("sin_capa")
    return TodayOut(
        date=today,
        city=forecast.city if forecast else city,
        weather=WeatherOut(**forecast.as_dict()) if forecast else None,
        outfit=OutfitOut(
            id=outfit.id, status=outfit.status, affinity=outfit.affinity, day_kind=outfit.day_kind, garments=garments_out
        )
        if outfit
        else None,
        missing=missing,
        notes=notes,
        in_laundry=db.scalar(select(func.count()).select_from(Garment).where(Garment.in_laundry.is_(True))) or 0,
        total=db.scalar(select(func.count()).select_from(Garment)) or 0,
    )


def _today_state(db: Session, regenerate: bool = False, replaced: Outfit | None = None) -> TodayOut:
    today = outfits.local_today()
    city = read_settings(db).city
    forecast = weather.today(city)
    outfit = _current(db, today)
    missing: list[str] = []
    notes: list[str] = []
    if outfit and outfit.status == PROPOSED and not _still_valid(db, outfit):
        outfit.status = REPLACED
        db.commit()
        outfit = None
    if outfit is None or regenerate:
        outfit, missing, notes = _generate(db, today, forecast, replaced)
    return _response(db, today, forecast, city, outfit, missing, notes)


@router.get("/today", response_model=TodayOut)
def get_today(db: Session = Depends(get_db)):
    """El tiempo y el outfit de hoy. Si aún no hay propuesta, la genera."""
    return _today_state(db)


@router.post("/today/next", response_model=TodayOut)
def next_outfit(body: NextIn, db: Session = Depends(get_db)):
    """«Generar otra propuesta» (sin opinar) o «Pasar» (no me gusta: cuenta como valoración)."""
    current = _current(db, outfits.local_today())
    if current and current.status == CHOSEN:
        raise HTTPException(409, "Ya has elegido el outfit de hoy")
    if current:
        current.status = DISCARDED if body.action == "pasar" else REPLACED
        already = db.scalar(select(Rating.id).where(Rating.outfit_id == current.id, Rating.liked.is_(False)))
        if body.action == "pasar" and not already:  # también enseña, pero menos: no sabemos el motivo
            db.add(Rating(garment_ids=current.garment_ids, liked=False, weight=0.5, reasons=[],
                          source="hoy", outfit_id=current.id))
        db.commit()
    return _today_state(db, regenerate=True, replaced=current)


@router.post("/today/choose", response_model=TodayOut)
def choose_outfit(db: Session = Depends(get_db)):
    """«Me gusta»: es el outfit de hoy. Se apunta un uso de cada prenda."""
    today = outfits.local_today()
    current = _current(db, today)
    if not current:  # aún no se había pedido la propuesta de hoy
        _today_state(db)
        current = _current(db, today)
    if not current:
        raise HTTPException(404, "No hay outfit que elegir")
    if current.status != CHOSEN:
        current.status = CHOSEN
        for garment_id in current.garment_ids:
            db.add(WearLog(garment_id=garment_id, worn_on=today, outfit_id=current.id))
        db.add(Rating(garment_ids=current.garment_ids, liked=True, weight=1.0, reasons=[],
                      source="hoy", outfit_id=current.id))
        db.commit()
    return _today_state(db)


@router.post("/today/unchoose", response_model=TodayOut)
def unchoose_outfit(db: Session = Depends(get_db)):
    """Deshace el «Me gusta»: vuelve a ser una propuesta y se quitan los usos que apuntó."""
    current = _current(db, outfits.local_today())
    if current and current.status == CHOSEN:
        current.status = PROPOSED
        db.query(WearLog).filter(WearLog.outfit_id == current.id).delete()
        db.query(Rating).filter(Rating.outfit_id == current.id, Rating.liked.is_(True)).delete()
        db.commit()
    return _today_state(db)
