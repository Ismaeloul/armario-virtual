from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import catalog

GarmentType = Literal[*catalog.TYPES]
Season = Literal[*catalog.SEASONS]
ColorName = Literal[*catalog.COLORS]
Pattern = Literal[*catalog.PATTERNS]
Style = Literal[*catalog.STYLES]
Closure = Literal[*catalog.CLOSURES]
Fit = Literal[*catalog.FITS]
Thickness = Literal[*catalog.THICKNESSES]
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
    closure: Closure | None = None
    hood: bool = False
    fit: Fit | None = None
    thickness: Thickness | None = None
    details: str = Field(default="", max_length=300)
    season: Season
    brand: str | None = Field(default=None, max_length=80)
    size: str | None = Field(default=None, max_length=20)
    notes: str = Field(default="", max_length=500)
    reference: str | None = Field(default=None, max_length=40)  # la de la tienda; la IA no la rellena

    _strip = field_validator("brand", "size", "reference", mode="before")(_clean_optional)


class GarmentDraft(GarmentFields):
    """Respuesta validada de la IA."""

    # Si dudaba entre dos colores para el principal, el otro candidato. No se guarda en la prenda:
    # solo sirve para avisar en el borrador.
    color_primary_alt: ColorName | None = None
    confidence: float = Field(ge=0, le=1)


class GarmentCreate(GarmentFields):
    photo_front: str = Field(pattern=PHOTO_ID)
    photo_back: str | None = Field(default=None, pattern=PHOTO_ID)
    photo_extra: str | None = Field(default=None, pattern=PHOTO_ID)
    photo_label: str | None = Field(default=None, pattern=PHOTO_ID)
    ai_provider: AIProvider | None = None
    ai_model: str | None = Field(default=None, max_length=60)
    ai_confidence: float | None = Field(default=None, ge=0, le=1)
    ai_draft: GarmentDraft | None = None  # la propuesta original de la IA, sin los retoques del usuario


class GarmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    type: GarmentType | None = None
    color_primary: Color | None = None
    colors_secondary: list[Color] | None = Field(default=None, max_length=4)
    pattern: Pattern | None = None
    style: Style | None = None
    closure: Closure | None = None
    hood: bool | None = None
    fit: Fit | None = None
    thickness: Thickness | None = None
    details: str | None = Field(default=None, max_length=300)
    season: Season | None = None
    brand: str | None = Field(default=None, max_length=80)
    size: str | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=500)
    reference: str | None = Field(default=None, max_length=40)
    favorite: bool | None = None
    in_laundry: bool | None = None
    on_order: bool | None = None  # False = «Ya me ha llegado»


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
    closure: str | None
    hood: bool
    fit: str | None
    thickness: str | None
    details: str
    season: str
    brand: str | None
    size: str | None
    notes: str
    reference: str | None = None
    store_name: str | None = None  # de qué tienda vino, si entró por Compras
    store_url: str | None = None
    photo_front: Photo
    photo_back: Photo | None
    photo_extra: Photo | None
    photo_label: Photo | None
    photos_edited: bool = False  # Codex las redibujó como «de tienda» (se puede volver a las de la cámara)
    in_laundry: bool
    laundry_since: datetime | None
    favorite: bool
    on_order: bool = False  # pedida, pendiente de llegar: no se propone
    ordered_at: datetime | None = None
    ai_provider: str | None
    ai_model: str | None = None
    ai_confidence: float | None
    wear_count: int
    last_worn_on: date | None
    created_at: datetime
    updated_at: datetime


class AnalyzeResponse(BaseModel):
    """Las fotos se guardan siempre; el borrador puede faltar si la IA falla."""

    photo_front: Photo
    photo_back: Photo | None
    photo_extra: Photo | None
    photo_label: Photo | None
    draft: GarmentDraft | None
    provider: str | None  # quién analizó de verdad
    model: str | None = None  # con qué modelo, si se sabe
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
    codex_model: str  # vacío = el que Codex use por defecto
    codex_effort: str  # vacío = el del modelo
    # Los de traducir los nombres de las tiendas, aparte (puede ser un modelo pequeño).
    codex_translate_model: str
    codex_translate_effort: str
    city: str
    notify_enabled: bool
    notify_time: str


class SettingsUpdate(BaseModel):
    theme: Theme | None = None
    ai_provider: AIProvider | None = None
    codex_model: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._-]{0,40}$")
    codex_effort: Literal["", "low", "medium", "high"] | None = None
    codex_translate_model: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._-]{0,40}$")
    codex_translate_effort: Literal["", "low", "medium", "high"] | None = None
    city: str | None = Field(default=None, min_length=1, max_length=80)
    notify_enabled: bool | None = None
    notify_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    # Solo escritura: nunca se devuelve. Cadena vacía = borrar la clave guardada.
    anthropic_api_key: str | None = Field(default=None, max_length=300)

    @field_validator("city", mode="before")
    @classmethod
    def _strip_city(cls, v):
        return v.strip() if isinstance(v, str) else v


class AIStatus(BaseModel):
    codex_installed: bool
    codex_logged_in: bool
    claude_configured: bool


class CodexLogin(BaseModel):
    state: Literal["idle", "pending", "done", "failed"]
    url: str | None = None
    code: str | None = None
    error: str | None = None
    expires_in: int | None = None


class Correction(BaseModel):
    """Un campo que el usuario cambió respecto a lo que propuso la IA."""

    garment_id: int
    garment: str
    provider: str | None
    field: str
    ai: object
    saved: object
    photo: str


class CorrectionsReport(BaseModel):
    analyzed: int  # prendas guardadas a partir de un borrador de la IA
    untouched: int  # de ellas, las que se guardaron sin tocar nada
    by_field: dict[str, int]
    corrections: list[Correction]


class UsageWindow(BaseModel):
    used_percent: float | None
    window_minutes: int | None
    resets_at: int | None


class CodexUsage(BaseModel):
    plan: str | None
    allowed: bool
    primary: UsageWindow | None  # ventana corta (5 horas)
    secondary: UsageWindow | None  # ventana larga (semanal)
