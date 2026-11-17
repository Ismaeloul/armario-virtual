"""Pestaña Gustos: valorar combinaciones para que el algoritmo aprenda qué pega y qué no."""
import itertools
import random
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Garment, Rating
from ..schemas import GarmentOut
from ..services import outfits, taste
from .garments import _to_out, _wear_stats

router = APIRouter(prefix="/api", tags=["gustos"])

Reason = Literal[*taste.REASONS]


class Combo(BaseModel):
    garments: list[GarmentOut]
    affinity: int


class TasteOut(BaseModel):
    combo: Combo | None  # None = no queda nada por valorar (o faltan prendas)
    rated: int
    liked: int
    remaining: int
    learned: dict  # parejas de colores que más y menos le gustan


class RateIn(BaseModel):
    garment_ids: list[int] = Field(min_length=2, max_length=4)
    liked: bool
    reasons: list[Reason] = Field(default_factory=list)
    culprit_ids: list[int] = Field(default_factory=list, max_length=4)  # prendas que estropean el conjunto


def piece(g: Garment) -> taste.Piece:
    return taste.Piece(
        id=g.id, type=g.type, category=g.category, color=g.color_primary, style=g.style, pattern=g.pattern,
        details=f"{g.name} {g.details or ''}",
    )


def load_taste(db: Session) -> taste.Taste:
    """Reconstruye lo aprendido a partir de todas las valoraciones guardadas."""
    garments = {g.id: g for g in db.scalars(select(Garment))}
    votes = []
    for rating in db.scalars(select(Rating).order_by(Rating.id)):
        pieces = [piece(garments[i]) for i in rating.garment_ids if i in garments]
        if len(pieces) >= 2:  # si se borraron prendas, lo que queda sigue enseñando algo
            votes.append(
                taste.Vote(
                    pieces=pieces,
                    liked=rating.liked,
                    weight=rating.weight,
                    reasons=tuple(rating.reasons or ()),
                    culprit_ids=frozenset(
                        rating.culprit_ids or ([rating.culprit_id] if rating.culprit_id else [])
                    ),
                )
            )
    return taste.build(votes)


def _all_combos(garments: list[Garment]) -> list[list[Garment]]:
    """Todas las combinaciones posibles: arriba + abajo, con y sin calzado y capa. La lavadora aquí da igual."""
    by_category: dict[str, list[Garment]] = {}
    for g in garments:
        by_category.setdefault(g.category, []).append(g)
    tops, bottoms = by_category.get("parte_superior", []), by_category.get("parte_inferior", [])
    shoes = by_category.get("calzado", []) or [None]
    layers = [None, *by_category.get("capa_exterior", [])]
    return [
        [p for p in (layer, top, bottom, shoe) if p is not None]
        for top, bottom, shoe, layer in itertools.product(tops, bottoms, shoes, layers)
    ]


def _state(db: Session) -> TasteOut:
    garments = list(db.scalars(select(Garment)))
    ratings = [r for r in db.scalars(select(Rating)) if r.source == "gustos"]
    rated_sets = {frozenset(r.garment_ids) for r in ratings}
    learned = load_taste(db)

    pending = [c for c in _all_combos(garments) if frozenset(g.id for g in c) not in rated_sets]
    combo = None
    if pending:
        # Primero las combinaciones que alguien se pondría: sin mezclar prendas de verano con las de invierno.
        coherent = [c for c in pending if not {"verano", "invierno"} <= {g.season for g in c}]
        chosen = random.choice(coherent or pending)
        stats = _wear_stats(db, [g.id for g in chosen])
        combo = Combo(
            garments=[_to_out(g, stats) for g in chosen],
            affinity=outfits.combo_affinity([piece(g) for g in chosen], learned),
        )
    return TasteOut(
        combo=combo,
        rated=len(ratings),
        liked=sum(1 for r in ratings if r.liked),
        remaining=len(pending),
        learned=learned.summary(),
    )


@router.get("/taste/next", response_model=TasteOut)
def next_combo(db: Session = Depends(get_db)):
    """Una combinación aún sin valorar, con la afinidad que el algoritmo le calcula ahora mismo."""
    return _state(db)


@router.post("/taste/rate", response_model=TasteOut)
def rate(body: RateIn, db: Session = Depends(get_db)):
    """Guarda la valoración y devuelve la siguiente combinación."""
    found = {g.id for g in db.scalars(select(Garment).where(Garment.id.in_(body.garment_ids)))}
    if found != set(body.garment_ids):
        raise HTTPException(404, "Alguna prenda de la combinación ya no existe")
    if not set(body.culprit_ids) <= found:
        raise HTTPException(422, "Alguna prenda señalada no está en la combinación")
    db.add(
        Rating(
            garment_ids=body.garment_ids,
            liked=body.liked,
            weight=1.0,
            reasons=[] if body.liked else list(dict.fromkeys(body.reasons)),
            culprit_ids=[] if body.liked else list(dict.fromkeys(body.culprit_ids)),
            source="gustos",
        )
    )
    db.commit()
    return _state(db)


@router.delete("/taste", status_code=204)
def forget(db: Session = Depends(get_db)):
    """Borra todo lo aprendido (valoraciones de Gustos y de Hoy)."""
    db.query(Rating).delete()
    db.commit()
