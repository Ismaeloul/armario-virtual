from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import catalog

GarmentType = Literal[*catalog.TYPES]
Season = Literal[*catalog.SEASONS]
ColorName = Literal[*catalog.COLORS]
Pattern = Literal[*catalog.PATTERNS]
Style = Literal[*catalog.STYLES]
AIProvider = Literal[*catalog.AI_PROVIDERS]
Theme = Literal[*catalog.THEMES]

PHOTO_ID = r"^[0-9a-f]{32}$"


def _clean_optional(v):
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


class Color(BaseModel):
    name: ColorName
    hex: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class GarmentFields(BaseModel):
    """Atributos de una prenda: lo que propone la IA y lo que se edita a mano."""

    name: str = Field(min_length=1, max_length=120)
    type: GarmentType
    color_primary: Color
    colors_secondary: list[Color] = Field(default_factory=list, max_length=4)
    pattern: Pattern
    style: Style
    details: str = Field(default="", max_length=300)
    season: Season
    brand: str | None = Field(default=None, max_length=80)
    size: str | None = Field(default=None, max_length=20)
    notes: str = Field(default="", max_length=500)

    _strip = field_validator("brand", "size", mode="before")(_clean_optional)


class GarmentDraft(GarmentFields):
    """Respuesta validada de la IA."""

    confidence: float = Field(ge=0, le=1)


class GarmentCreate(GarmentFields):
    photo_front: str = Field(pattern=PHOTO_ID)
    photo_back: str | None = Field(default=None, pattern=PHOTO_ID)
    ai_provider: AIProvider | None = None
    ai_confidence: float | None = Field(default=None, ge=0, le=1)


class GarmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    type: GarmentType | None = None
    color_primary: Color | None = None
    colors_secondary: list[Color] | None = Field(default=None, max_length=4)
    pattern: Pattern | None = None
    style: Style | None = None
    details: str | None = Field(default=None, max_length=300)
    season: Season | None = None
    brand: str | None = Field(default=None, max_length=80)
    size: str | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=500)
    favorite: bool | None = None
    in_laundry: bool | None = None


class Photo(BaseModel):
    id: str
    url: str
    thumb_url: str


class GarmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: str
    category: str
    color_primary: Color
    colors_secondary: list[Color]
    pattern: str
    style: str
    details: str
    season: str
    brand: str | None
    size: str | None
    notes: str
    photo_front: Photo
    photo_back: Photo | None
    in_laundry: bool
    laundry_since: datetime | None
    favorite: bool
    ai_provider: str | None
    ai_confidence: float | None
    wear_count: int
    last_worn_on: date | None
    created_at: datetime
    updated_at: datetime


class AnalyzeResponse(BaseModel):
    """Las fotos se guardan siempre; el borrador puede faltar si la IA falla."""

    photo_front: Photo
    photo_back: Photo | None
    draft: GarmentDraft | None
    provider: str | None  # quién analizó de verdad
    fallback_used: bool  # True si no fue el proveedor elegido en Ajustes
    error: str | None


class Summary(BaseModel):
    total: int
    in_laundry: int
    by_type: dict[str, int]
    by_category: dict[str, int]


class WearIn(BaseModel):
    worn_on: date | None = None


class SettingsOut(BaseModel):
    theme: Theme
    ai_provider: AIProvider
    city: str
    notify_enabled: bool
    notify_time: str


class SettingsUpdate(BaseModel):
    theme: Theme | None = None
    ai_provider: AIProvider | None = None
    city: str | None = Field(default=None, min_length=1, max_length=80)
    notify_enabled: bool | None = None
    notify_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
