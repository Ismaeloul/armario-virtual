"""Pestaña Compras: novedades de las tiendas puntuadas contra el armario.

La app solo enlaza a la página del producto: nunca compra ni guarda datos de pago.
"""
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import catalog
from ..db import get_db
from ..models import ShopItem
from ..schemas import Photo
from ..services import shopping, shops, storage
from .settings import read_settings

router = APIRouter(prefix="/api/shop", tags=["compras"])


class ShopReason(BaseModel):
    text: str
    kind: Literal["pro", "contra"]


class ShopSize(BaseModel):
    name: str
    in_stock: bool


class ShopItemOut(BaseModel):
    id: int
    store: str
    store_name: str
    name: str
    price_cents: int
    url: str
    store_color: str
    type: str
    category: str
    color: str
    photos: list[Photo]
    score: float
    reasons: list[ShopReason]
    status: str
    sizes: list[ShopSize]
    liked_at: datetime | None
    expires_at: datetime | None
    expires_soon: bool


class ShopCategoryOut(BaseModel):
    slug: str
    label: str
    enabled: bool


class ShopStatusOut(BaseModel):
    """Cómo fue la última consulta a una tienda (panel «Tiendas»)."""

    state: Literal["ok", "failed", "never"]  # funciona · falló · sin consultar todavía
    at: datetime | None
    found: int  # productos que trajo el catálogo
    added: int  # propuestas nuevas que salieron de ahí
    failed: int  # peticiones que fallaron
    error: str | None  # el primer fallo, en claro («Camisas: HTTP 403»)


class ShopStoreOut(BaseModel):
    key: str
    name: str
    enabled: bool
    categories: list[ShopCategoryOut]
    weekday: int  # día de la semana en que se consulta (lunes = 0)
    status: ShopStatusOut
    next_check: date | None  # cuándo se consultará sola (None si está desactivada)


class ShopMoreOut(BaseModel):
    """Cómo fue el último «Ver más» desde la última consulta semanal."""

    added: int  # propuestas que trajo
    low: bool  # su nota media es baja: lo que viene ya encaja menos
    error: str | None  # el primer fallo, en claro


class ShopState(BaseModel):
    stores: list[ShopStoreOut]
    running: bool  # hay una consulta o un «Ver más» en marcha
    job: Literal["consulta", "mas"] | None  # cuál de las dos
    pending: int  # propuestas por ver
    liked: int
    last_more: ShopMoreOut | None


class ShopSettingsIn(BaseModel):
    store: str
    enabled: bool | None = None
    categories: list[str] | None = Field(default=None, max_length=50)


class RefreshIn(BaseModel):
    store: str | None = None  # None = todas las activadas


class MoreIn(BaseModel):
    store: str | None = None  # None = todas las activadas
    category: str | None = None  # None = todo tipo de prenda


class ReasonIn(BaseModel):
    reason: Literal["estilo", "color", "caro", "ya_tengo"] | None = None


class ShopNext(BaseModel):
    item: ShopItemOut | None
    remaining: int  # cuántas quedan con este filtro, contando esta
    more: int  # candidatos que «Ver más» aún puede traer con este filtro
    can_undo: bool  # hay una decisión que «Volver» puede deshacer


def _check_filter(store: str | None, category: str | None) -> None:
    if store is not None and store not in shops.CONNECTORS:
        raise HTTPException(404, "Tienda desconocida")
    if category is not None and category not in catalog.CATEGORIES:
        raise HTTPException(422, "Tipo de prenda desconocido")


class Filter:
    """El filtro de Descubrir: una tienda y un tipo de prenda (nuestras categorías). Va en la URL."""

    def __init__(self, store: str | None = Query(default=None), category: str | None = Query(default=None)):
        _check_filter(store, category)
        self.store, self.category = store, category


class BoughtIn(BaseModel):
    size: str | None = Field(default=None, max_length=20)


class BoughtOut(BaseModel):
    garment_id: int
    analyzed: bool  # False = la IA falló y la prenda se creó con los datos estimados


def _to_out(item: ShopItem) -> ShopItemOut:
    connector = shops.CONNECTORS.get(item.store)
    return ShopItemOut(
        id=item.id,
        store=item.store,
        store_name=connector.name if connector else item.store.capitalize(),
        name=item.name,
        price_cents=item.price_cents,
        url=item.url,
        store_color=item.store_color,
        type=item.type,
        category=item.category,
        color=item.color,
        photos=[storage.to_schema(photo_id) for photo_id in item.photos or []],
        score=item.score,
        reasons=item.reasons or [],
        status=item.status,
        sizes=item.sizes or [],
        liked_at=item.liked_at,
        expires_at=item.expires_at,
        expires_soon=item.status == shopping.LIKED and shopping.expires_soon(item),
    )


def _count(db: Session, status: str, stores: list[str] | None = None, category: str | None = None) -> int:
    stmt = select(func.count()).select_from(ShopItem).where(ShopItem.status == status)
    if stores is not None:
        stmt = stmt.where(ShopItem.store.in_(stores))
    if category is not None:
        stmt = stmt.where(ShopItem.category == category)
    return db.scalar(stmt) or 0


def _state(db: Session) -> ShopState:
    enabled = shopping.enabled_stores(db)
    stores = []
    for key, connector in shops.CONNECTORS.items():
        active = set(shopping.active_categories(db, key))
        status = shopping.store_status(db, key) or {}
        consulted = bool(status.get("at"))
        stores.append(
            ShopStoreOut(
                key=key,
                name=connector.name,
                enabled=key in enabled,
                weekday=getattr(connector, "refresh_weekday", 0),
                status=ShopStatusOut(
                    state=("ok" if status.get("ok") else "failed") if consulted else "never",
                    at=status.get("at") if consulted else None,
                    found=int(status.get("found", 0)),
                    added=int(status.get("added", 0)),
                    failed=int(status.get("failed", 0)),
                    error=status.get("error"),
                ),
                next_check=shopping.next_check(db, key) if key in enabled else None,
                categories=[
                    ShopCategoryOut(slug=slug, label=label, enabled=slug in active)
                    for slug, label in connector.categories.items()
                ],
            )
        )
    more = shopping.last_more(db)
    return ShopState(
        stores=stores,
        running=shopping.is_running(),
        job=shopping.running_job(),
        pending=_count(db, shopping.NEW, enabled),
        liked=_count(db, shopping.LIKED),
        last_more=ShopMoreOut(added=more.get("added", 0), low=bool(more.get("low")), error=more.get("error"))
        if more
        else None,
    )


def _next(db: Session, only: Filter, first: ShopItem | None = None) -> ShopNext:
    """La propuesta con mejor nota entre las que quedan por ver: una sola lista, venga de la tienda que
    venga, con el filtro de tienda y de tipo de prenda. `first` adelanta una concreta (la recién deshecha)."""
    stores = [s for s in shopping.enabled_stores(db) if only.store in (None, s)]
    stmt = select(ShopItem).where(ShopItem.status == shopping.NEW, ShopItem.store.in_(stores))
    if only.category is not None:
        stmt = stmt.where(ShopItem.category == only.category)
    item = first or db.scalars(stmt.order_by(ShopItem.score.desc(), ShopItem.id).limit(1)).first()
    return ShopNext(
        item=_to_out(item) if item else None,
        remaining=_count(db, shopping.NEW, stores, only.category),
        more=len(shopping.candidates_left(db, store=only.store, category=only.category)),
        can_undo=shopping.last_decision(db) is not None,
    )


def _get_or_404(db: Session, item_id: int) -> ShopItem:
    item = db.get(ShopItem, item_id)
    if not item:
        raise HTTPException(404, "Este producto ya no está")
    return item


@router.get("/state", response_model=ShopState)
def state(db: Session = Depends(get_db)):
    return _state(db)


@router.patch("/settings", response_model=ShopState)
def update_settings(body: ShopSettingsIn, db: Session = Depends(get_db)):
    """Activa o desactiva una tienda y elige qué categorías interesan."""
    if body.store not in shops.CONNECTORS:
        raise HTTPException(404, "Tienda desconocida")
    shopping.set_store(db, body.store, body.enabled, body.categories)
    return _state(db)


@router.post("/refresh", response_model=ShopState, status_code=202)
def refresh(body: RefreshIn | None = None, db: Session = Depends(get_db)):
    """«Consultar ahora»: lanza la consulta en segundo plano (de una tienda o de todas las activadas) y
    responde ya. Vale cualquier día. Si hay una en marcha, no lanza otra."""
    enabled = shopping.enabled_stores(db)
    store = body.store if body else None
    if store is not None and store not in shops.CONNECTORS:
        raise HTTPException(404, "Tienda desconocida")
    if not enabled or (store is not None and store not in enabled):
        raise HTTPException(409, "Activa primero la tienda")
    shopping.start_refresh([store] if store else None)
    return _state(db)


@router.post("/more", response_model=ShopState, status_code=202)
def more(body: MoreIn | None = None, db: Session = Depends(get_db)):
    """«Ver más»: trae en segundo plano la siguiente tanda de los candidatos guardados (con el filtro
    que se le pase) y responde ya. No consulta el catálogo. Si hay una tanda en marcha, no lanza otra."""
    body = body or MoreIn()
    _check_filter(body.store, body.category)
    enabled = shopping.enabled_stores(db)
    if not enabled or (body.store is not None and body.store not in enabled):
        raise HTTPException(409, "Activa primero la tienda")
    shopping.start_more(body.store, body.category)
    return _state(db)


@router.get("/next", response_model=ShopNext)
def next_item(only: Filter = Depends(), db: Session = Depends(get_db)):
    return _next(db, only)


@router.post("/items/{item_id}/like", response_model=ShopNext)
def like(item_id: int, only: Filter = Depends(), db: Session = Depends(get_db)):
    """Me gusta: pasa a «Me gustan» y devuelve la siguiente propuesta."""
    item = _get_or_404(db, item_id)
    if item.status == shopping.NEW:
        shopping.like(db, item)
    elif item.status != shopping.LIKED:  # un doble toque no es un error
        raise HTTPException(409, "Este producto ya no está entre las propuestas")
    return _next(db, only)


@router.post("/items/{item_id}/dislike", response_model=ShopNext)
def dislike(item_id: int, only: Filter = Depends(), db: Session = Depends(get_db)):
    """No me gusta: no se vuelve a proponer. Devuelve la siguiente propuesta."""
    item = _get_or_404(db, item_id)
    if item.status == shopping.NEW:
        shopping.dislike(db, item)
    elif item.status != shopping.DISCARDED:
        raise HTTPException(409, "Este producto ya no está entre las propuestas")
    return _next(db, only)


@router.post("/items/{item_id}/reason", status_code=204)
def reason(item_id: int, body: ReasonIn, db: Session = Depends(get_db)):
    """Por qué no gustó (opcional): estilo, color, caro o «ya tengo algo así». Afina lo que se aprende."""
    item = _get_or_404(db, item_id)
    if item.status != shopping.DISCARDED or item.liked_at is not None:
        raise HTTPException(409, "Este producto no está descartado")
    shopping.set_reason(db, item, body.reason)


@router.post("/undo", response_model=ShopNext)
def undo(only: Filter = Depends(), db: Session = Depends(get_db)):
    """«Volver»: deshace la última decisión de la tanda y vuelve a enseñar esa propuesta. Se puede
    repetir para ir hacia atrás."""
    item = shopping.undo(db)
    if item is None:
        raise HTTPException(409, "No hay nada que deshacer")
    return _next(db, only, first=item)


@router.get("/liked", response_model=list[ShopItemOut])
def liked(db: Session = Depends(get_db)):
    shopping.expire_old(db)
    items = db.scalars(
        select(ShopItem).where(ShopItem.status == shopping.LIKED).order_by(ShopItem.liked_at.desc(), ShopItem.id.desc())
    )
    return [_to_out(item) for item in items]


@router.delete("/items/{item_id}", status_code=204)
def remove(item_id: int, db: Session = Depends(get_db)):
    """Quitar de «Me gustan»."""
    item = _get_or_404(db, item_id)
    if item.status == shopping.LIKED:
        shopping.remove_liked(db, item)
    elif item.status != shopping.DISCARDED:
        raise HTTPException(409, "Este producto no está en «Me gustan»")


@router.post("/items/{item_id}/bought", response_model=BoughtOut)
def bought(item_id: int, body: BoughtIn, db: Session = Depends(get_db)):
    """«La he comprado»: analiza las fotos guardadas y pasa la prenda al armario con la talla elegida."""
    item = _get_or_404(db, item_id)
    if item.status == shopping.BOUGHT and item.garment_id:  # doble toque: la prenda ya está creada
        return BoughtOut(garment_id=item.garment_id, analyzed=item.ai_draft is not None)
    if item.status not in (shopping.NEW, shopping.LIKED):
        raise HTTPException(409, "Este producto ya no está disponible")
    size = (body.size or "").strip() or None
    try:
        garment, analyzed = shopping.buy(db, item, size, read_settings(db).ai_provider)
    except shopping.CannotBuy as exc:
        raise HTTPException(409, str(exc)) from exc
    return BoughtOut(garment_id=garment.id, analyzed=analyzed)
