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
    details: Mapped[str] = mapped_column(Text, default="")
    season: Mapped[str] = mapped_column(String(20), index=True)
    brand: Mapped[str | None] = mapped_column(String(80), nullable=True)
    size: Mapped[str | None] = mapped_column(String(20), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    # Identificadores de foto (ver services/storage.py). Las *_original guardan el archivo
    # tal como se subió, para cuando se quite el fondo.
    photo_front: Mapped[str] = mapped_column(String(32))
    photo_back: Mapped[str | None] = mapped_column(String(32), nullable=True)
    photo_front_original: Mapped[str | None] = mapped_column(String(64), nullable=True)
    photo_back_original: Mapped[str | None] = mapped_column(String(64), nullable=True)

    in_laundry: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    laundry_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)

    ai_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ai_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    wears: Mapped[list["WearLog"]] = relationship(back_populates="garment", cascade="all, delete-orphan")


class WearLog(Base):
    """Cada vez que se usa una prenda. El contador y la última vez se derivan de aquí."""

    __tablename__ = "wear_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    garment_id: Mapped[int] = mapped_column(ForeignKey("garments.id", ondelete="CASCADE"), index=True)
    worn_on: Mapped[date] = mapped_column(Date, index=True)

    garment: Mapped[Garment] = relationship(back_populates="wears")


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
