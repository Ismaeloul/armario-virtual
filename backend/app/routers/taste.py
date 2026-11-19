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
from ..services import outfits, style_rules, taste
from .garments import _to_out, _wear_stats

router = APIRouter(prefix="/api", tags=["gustos"])

Reason = Literal[*taste.REASONS]

# Entre cuántas combinaciones pendientes, cogidas al azar, se elige la que más enseña.
SAMPLE = 12
# Intentos de dar al azar con una pendiente antes de recorrerlas todas (solo pasa cuando quedan pocas).
TRIES = 300
# Un outfit que el usuario monta él mismo («Tus outfits») enseña el doble que un «me gusta» a una
# combinación propuesta: no es que le parezca bien, es que lo ha elegido y se lo ha puesto.
OWN_WEIGHT = 2.0
OWN = "propio"


class Combo(BaseModel):
    garments: list[GarmentOut]
    affinity: int


class TasteOut(BaseModel):
    combo: Combo | None  # None = no queda nada por valorar (o faltan prendas)
    rated: int
    liked: int
    remaining: int
    learned: dict  # parejas de colores que más y menos le gustan
    own: int = 0  # outfits montados por el usuario


class OwnIn(BaseModel):
    garment_ids: list[int] = Field(min_length=2, max_length=6)


class OwnOut(BaseModel):
    id: int
    garments: list[GarmentOut]
    affinity: int


class RateIn(BaseModel):
    garment_ids: list[int] = Field(min_length=2, max_length=4)
    liked: bool
    reasons: list[Reason] = Field(default_factory=list)
    culprit_ids: list[int] = Field(default_factory=list, max_length=4)  # prendas que estropean el conjunto
    # «Me gusta y guardar»: además de gustar, va a «Tus outfits» del Armario y cuenta el doble.
    save: bool = False


def piece(g: Garment) -> taste.Piece:
    return taste.Piece(
        id=g.id, type=g.type, category=g.category, color=g.color_primary, style=g.style, pattern=g.pattern,
        details=f"{g.name} {g.details or ''}", closure=g.closure, fit=g.fit, thickness=g.thickness, hood=g.hood,
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


def _slots(garments: list[Garment]) -> tuple[list, list, list, list]:
    """Las prendas por hueco: arriba, abajo, calzado (o ninguno si no hay) y capa (o ninguna)."""
    by_category: dict[str, list[Garment]] = {}
    for g in garments:
        by_category.setdefault(g.category, []).append(g)
    return (
        by_category.get("parte_superior", []),
        by_category.get("parte_inferior", []),
        by_category.get("calzado", []) or [None],
        [None, *by_category.get("capa_exterior", [])],
    )


def _allowed(top: Garment, layer: Garment | None) -> bool:
    """Lo que el usuario ya dijo que no se pone no se pregunta: cazadora sobre sudadera con cremallera."""
    return layer is None or not style_rules.zip_clash(piece(layer), piece(top))


def _all_combos(garments: list[Garment]) -> list[list[Garment]]:
    """Todas las combinaciones posibles: arriba + abajo, con y sin capa, y con calzado si lo hay.

    La lavadora aquí da igual.
    """
    tops, bottoms, shoes, layers = _slots(garments)
    return [
        [p for p in (layer, top, bottom, shoe) if p is not None]
        for top, bottom, shoe, layer in itertools.product(tops, bottoms, shoes, layers)
        if _allowed(top, layer)
    ]


def _count_combos(garments: list[Garment]) -> int:
    """Cuántas hay, sin recorrerlas."""
    tops, bottoms, shoes, layers = _slots(garments)
    return sum(1 for top in tops for layer in layers if _allowed(top, layer)) * len(bottoms) * len(shoes)


def _is_combo(ids: frozenset[int], garments: dict[int, Garment], has_shoes: bool) -> bool:
    """¿Es una de las combinaciones de `_all_combos`? (Una valoración antigua puede ya no serlo.)"""
    if not ids <= garments.keys():
        return False
    slot = {garments[i].category: garments[i] for i in ids}
    return (
        len(slot) == len(ids)
        and "parte_superior" in slot
        and "parte_inferior" in slot
        and ("calzado" in slot) == has_shoes
        and _allowed(slot["parte_superior"], slot.get("capa_exterior"))
    )


def _coherent(combo: list[Garment]) -> bool:
    """Algo que alguien se pondría: sin mezclar prendas de verano con las de invierno."""
    return not {"verano", "invierno"} <= {g.season for g in combo}


def _pick(garments: list[Garment], rated: set[frozenset[int]], learned: taste.Taste) -> list[Garment] | None:
    """Una combinación sin valorar: entre unas cuantas al azar, la que más cosas nuevas enseña."""
    tops, bottoms, shoes, layers = _slots(garments)
    if not tops or not bottoms:
        return None
    found: dict[frozenset[int], list[Garment]] = {}
    for _ in range(TRIES):  # al azar, sin montar la lista entera: con un armario grande son muchos miles
        top, layer = random.choice(tops), random.choice(layers)
        combo = [p for p in (layer, top, random.choice(bottoms), random.choice(shoes)) if p is not None]
        ids = frozenset(g.id for g in combo)
        if ids not in rated and _allowed(top, layer) and _coherent(combo):
            found[ids] = combo
            if len(found) == SAMPLE:
                break
    candidates = list(found.values())
    if not candidates:  # quedan muy pocas (o ninguna): ahora sí se miran todas
        pending = [c for c in _all_combos(garments) if frozenset(g.id for g in c) not in rated]
        coherent = [c for c in pending if _coherent(c)]
        candidates = random.sample(coherent or pending, min(SAMPLE, len(coherent or pending)))
    if not candidates:
        return None
    return max(candidates, key=lambda combo: learned.novelty([piece(g) for g in combo]))


def _state(db: Session) -> TasteOut:
    # Lo pedido que aún no ha llegado también se valora (decisión del usuario): así se entrena ya con
    # la ropa que está por llegar. Solo Hoy la deja fuera.
    garments = list(db.scalars(select(Garment)))
    all_ratings = list(db.scalars(select(Rating)))
    ratings = [r for r in all_ratings if r.source == "gustos"]
    # Lo guardado en «Tus outfits» tampoco se vuelve a preguntar.
    rated_sets = {frozenset(r.garment_ids) for r in all_ratings if r.source in ("gustos", OWN)}
    learned = load_taste(db)

    by_id = {g.id: g for g in garments}
    has_shoes = any(g.category == "calzado" for g in garments)
    remaining = _count_combos(garments) - sum(1 for ids in rated_sets if _is_combo(ids, by_id, has_shoes))
    combo = None
    chosen = _pick(garments, rated_sets, learned) if remaining else None
    if chosen:
        stats = _wear_stats(db, [g.id for g in chosen])
        combo = Combo(
            garments=[_to_out(g, stats) for g in chosen],
            affinity=outfits.combo_affinity([piece(g) for g in chosen], learned),
        )
    return TasteOut(
        combo=combo,
        rated=len(ratings),
        liked=sum(1 for r in ratings if r.liked),
        remaining=remaining,
        learned=learned.summary(),
        own=sum(1 for r in db.scalars(select(Rating).where(Rating.source == OWN))),
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
    saved = body.liked and body.save
    db.add(
        Rating(
            garment_ids=body.garment_ids,
            liked=body.liked,
            weight=OWN_WEIGHT if saved else 1.0,
            reasons=[] if body.liked else list(dict.fromkeys(body.reasons)),
            culprit_ids=[] if body.liked else list(dict.fromkeys(body.culprit_ids)),
            source=OWN if saved else "gustos",
        )
    )
    db.commit()
    return _state(db)


@router.get("/taste/own", response_model=list[OwnOut])
def own_outfits(db: Session = Depends(get_db)):
    """Los outfits que el usuario ha montado él mismo, del último al primero."""
    learned = load_taste(db)
    garments = {g.id: g for g in db.scalars(select(Garment))}
    out = []
    for rating in db.scalars(select(Rating).where(Rating.source == OWN).order_by(Rating.id.desc())):
        pieces = [garments[i] for i in rating.garment_ids if i in garments]
        if len(pieces) < 2:
            continue  # se borraron prendas: ya no enseña nada
        stats = _wear_stats(db, [g.id for g in pieces])
        out.append(OwnOut(
            id=rating.id,
            garments=[_to_out(g, stats) for g in pieces],
            affinity=outfits.combo_affinity([piece(g) for g in pieces], learned),
        ))
    return out


@router.post("/taste/own", response_model=TasteOut)
def add_own(body: OwnIn, db: Session = Depends(get_db)):
    """«Añadir un outfit tuyo»: una combinación que el usuario ha montado y le queda bien. Cuenta como
    un «me gusta» con más peso."""
    ids = list(dict.fromkeys(body.garment_ids))
    found = list(db.scalars(select(Garment).where(Garment.id.in_(ids))))
    if len(found) != len(ids):
        raise HTTPException(404, "Alguna prenda del outfit ya no existe")
    categories = {g.category for g in found}
    if not {"parte_superior", "parte_inferior"} <= categories:
        raise HTTPException(422, "Un outfit lleva al menos una parte de arriba y una de abajo")
    if sum(g.category == "parte_inferior" for g in found) > 1 or sum(g.category == "calzado" for g in found) > 1:
        raise HTTPException(422, "Un outfit lleva una sola parte de abajo y un solo calzado")
    db.add(Rating(garment_ids=ids, liked=True, weight=OWN_WEIGHT, reasons=[], culprit_ids=[], source=OWN))
    db.commit()
    return _state(db)


@router.delete("/taste/own/{rating_id}", status_code=204)
def delete_own(rating_id: int, db: Session = Depends(get_db)):
    rating = db.get(Rating, rating_id)
    if rating is None or rating.source != OWN:
        raise HTTPException(404, "Ese outfit no existe")
    db.delete(rating)
    db.commit()


@router.delete("/taste", status_code=204)
def forget(db: Session = Depends(get_db)):
    """Borra todo lo aprendido (valoraciones de Gustos y de Hoy)."""
    db.query(Rating).delete()
    db.commit()
