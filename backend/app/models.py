from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Garment(Base):
    __tablename__ = "garments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(40), index=True)
    category: Mapped[str] = mapped_column(String(40), index=True)
    color_primary: Mapped[str] = mapped_column(String(40))
    color_primary_hex: Mapped[str] = mapped_column(String(7))
    colors_secondary: Mapped[list] = mapped_column(JSON, default=list)  # [{name, hex}]
    pattern: Mapped[str] = mapped_column(String(40))
    style: Mapped[str] = mapped_column(String(40))
    closure: Mapped[str | None] = mapped_column(String(20), nullable=True)
    hood: Mapped[bool | None] = mapped_column(nullable=True)
    fit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    thickness: Mapped[str | None] = mapped_column(String(20), nullable=True)
    details: Mapped[str] = mapped_column(Text, default="")
    season: Mapped[str] = mapped_column(String(20), index=True)
    brand: Mapped[str | None] = mapped_column(String(80), nullable=True)
    size: Mapped[str | None] = mapped_column(String(20), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    # La referencia de la prenda en su tienda («3918/300/800»). La pone Compras al comprarla y también
    # se puede escribir a mano. La tienda y el enlace solo los pone Compras.
    reference: Mapped[str | None] = mapped_column(String(40), nullable=True)
    store_name: Mapped[str | None] = mapped_column(String(40), nullable=True)
    store_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Identificadores de foto (ver services/storage.py). Las *_original guardan el archivo
    # tal como se subió, para cuando se quite el fondo.
    photo_front: Mapped[str] = mapped_column(String(32))
    photo_back: Mapped[str | None] = mapped_column(String(32), nullable=True)
    photo_front_original: Mapped[str | None] = mapped_column(String(64), nullable=True)
    photo_back_original: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Tercera vista opcional (en el calzado, el otro lateral).
    photo_extra: Mapped[str | None] = mapped_column(String(32), nullable=True)
    photo_extra_original: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Foto opcional de la etiqueta: de ahí salen la marca y la talla.
    photo_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    photo_label_original: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Si Codex redibujó las fotos como «de tienda»: las de la cámara, para poder volver a ellas.
    # {"front": id, "back": id, "extra": id} con las vistas que se cambiaron.
    photos_camera: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    in_laundry: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    laundry_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    # Pedida en la tienda y aún sin llegar: está en el armario, pero no se propone ni se puede usar
    # hasta que se marque como recibida. (None en las prendas anteriores a la columna = no.)
    on_order: Mapped[bool | None] = mapped_column(Boolean, default=False, nullable=True)
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    ai_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(60), nullable=True)  # modelo y esfuerzo usados
    ai_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Lo que propuso la IA, tal cual, para compararlo con lo que se guardó y afinar las instrucciones.
    ai_draft: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    wears: Mapped[list["WearLog"]] = relationship(back_populates="garment", cascade="all, delete-orphan")


class WearLog(Base):
    """Cada vez que se usa una prenda. El contador y la última vez se derivan de aquí."""

    __tablename__ = "wear_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    garment_id: Mapped[int] = mapped_column(ForeignKey("garments.id", ondelete="CASCADE"), index=True)
    worn_on: Mapped[date] = mapped_column(Date, index=True)
    # Si el uso lo apuntó un outfit del día (para poder deshacerlo).
    outfit_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    garment: Mapped[Garment] = relationship(back_populates="wears")


class Outfit(Base):
    """Cada propuesta de outfit y qué se hizo con ella. De aquí aprenderá el algoritmo de la Fase 3."""

    __tablename__ = "outfits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    garment_ids: Mapped[list] = mapped_column(JSON)
    # propuesto · elegido (Me gusta) · descartado (Pasar) · sustituido (Generar otra)
    status: Mapped[str] = mapped_column(String(20), index=True)
    affinity: Mapped[int] = mapped_column(Integer, default=0)
    day_kind: Mapped[str] = mapped_column(String(20), default="templado")
    weather: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # el tiempo que hacía
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Rating(Base):
    """Una valoración de una combinación: de aquí aprende el algoritmo qué pega y qué no."""

    __tablename__ = "ratings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    garment_ids: Mapped[list] = mapped_column(JSON)
    liked: Mapped[bool] = mapped_column(Boolean)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    reasons: Mapped[list] = mapped_column(JSON, default=list)  # por qué no gustó
    culprit_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # (antiguo: una sola prenda)
    culprit_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)  # las prendas que estropean el conjunto
    source: Mapped[str] = mapped_column(String(20), default="gustos")  # "gustos" o "hoy"
    outfit_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ShopItem(Base):
    """Un producto de una tienda propuesto en la pestaña Compras, y qué se hizo con él.

    Se guarda para siempre aunque se descarte o caduque: así no se vuelve a proponer. La excepción son
    los «candidatos»: el catálogo entero de la última consulta, sin fotos, del que sale «Ver más». Esos
    se renuevan en cada consulta semanal.
    """

    __tablename__ = "shop_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store: Mapped[str] = mapped_column(String(20), index=True)
    product_ref: Mapped[str] = mapped_column(String(80), unique=True, index=True)  # producto + color
    name: Mapped[str] = mapped_column(String(160))
    price_cents: Mapped[int] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(Text)
    store_color: Mapped[str] = mapped_column(String(60), default="")
    store_color_hex: Mapped[str | None] = mapped_column(String(7), nullable=True)
    section: Mapped[str] = mapped_column(String(80), default="")  # categoría de la tienda
    store_data: Mapped[dict] = mapped_column(JSON, default=dict)  # lo que el conector necesita para el detalle

    # Estimación sin IA de nuestros campos cerrados.
    type: Mapped[str] = mapped_column(String(40))
    category: Mapped[str] = mapped_column(String(40))
    color: Mapped[str] = mapped_column(String(40))
    pattern: Mapped[str] = mapped_column(String(40))
    style: Mapped[str] = mapped_column(String(40))
    season: Mapped[str] = mapped_column(String(20))
    details: Mapped[str] = mapped_column(Text, default="")

    # Ids de foto de services/storage.py (delante, detrás, otra vista). Al comprar pasan a la prenda.
    photos: Mapped[list] = mapped_column(JSON, default=list)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    reasons: Mapped[list] = mapped_column(JSON, default=list)  # [{"text": …, "kind": "pro" | "contra"}]
    # candidato (en el catálogo, sin enseñar) · nuevo · gustado · descartado · comprado · caducado ·
    # buscado (traído por el buscador de referencias y aún sin guardar: no sale en Descubrir) ·
    # variante (otro color de una propuesta, apartado al elegir color en Descubrir: ni sale ni cuenta)
    status: Mapped[str] = mapped_column(String(20), index=True)
    batch: Mapped[date] = mapped_column(Date, index=True)  # la tanda en la que llegó
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    liked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # La última vez que salió en el listado de la tienda. Al terminar de leer una sección entera, sus
    # candidatos que no han salido desde que empezó el recorrido es que la tienda ya no los tiene.
    listed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Cuándo se dijo me gusta / no me gusta, si aún se puede deshacer («Volver») y por qué se descartó.
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    can_undo: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)
    discard_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)  # estilo · color · caro · ya_tengo
    # En un «buscado» que ya existía (descartado, caducado…): el estado al que vuelve si no se hace nada.
    prev_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True)
    sizes: Mapped[list] = mapped_column(JSON, default=list)  # [{"name": "M", "in_stock": true}]
    garment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # si se compró
    ai_draft: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # lo que dijo la IA al comprarla
    # Los colores en los que existe (este incluido), como los da el conector (ShopDetail.siblings).
    # None = todavía no se sabe: se rellena la próxima vez que se pida su ficha.
    siblings: Mapped[list | None] = mapped_column(JSON, nullable=True)
    composition: Mapped[str | None] = mapped_column(Text, nullable=True)  # de qué está hecha, si la tienda lo dice
    # La marca, en las tiendas de varias marcas (Courir, JD Sports). Al comprarla, es la de la prenda.
    brand: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # El código de fabricante como clave («CW2288111»), en las tiendas de zapatillas que lo dicen: la misma
    # zapatilla en dos tiendas no se propone dos veces y el visor dice «También en…». None si no se sabe.
    maker_code: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    # Traducción al español de lo que la tienda dice en otro idioma. Lo original (name, store_color,
    # composition) no se toca: es lo que se puntúa y lo que sirve para buscarlo en la tienda.
    name_es: Mapped[str | None] = mapped_column(String(160), nullable=True)
    store_color_es: Mapped[str | None] = mapped_column(String(60), nullable=True)
    composition_es: Mapped[str | None] = mapped_column(Text, nullable=True)
    translated: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # True = ya traducido


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
