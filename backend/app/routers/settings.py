from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import catalog
from ..db import get_db
from ..models import Setting
from ..schemas import SettingsOut, SettingsUpdate

router = APIRouter(prefix="/api", tags=["ajustes"])

DEFAULTS = {
    "theme": "sistema",
    "ai_provider": "codex",
    "city": "Argenteuil",
    "notify_enabled": "true",
    "notify_time": "07:30",
}


def read_settings(db: Session) -> SettingsOut:
    values = dict(DEFAULTS)
    values.update({s.key: s.value for s in db.query(Setting).all() if s.key in DEFAULTS})
    return SettingsOut(
        theme=values["theme"],
        ai_provider=values["ai_provider"],
        city=values["city"],
        notify_enabled=values["notify_enabled"] == "true",
        notify_time=values["notify_time"],
    )


@router.get("/settings", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db)):
    return read_settings(db)


@router.patch("/settings", response_model=SettingsOut)
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db)):
    for key, value in body.model_dump(exclude_none=True).items():
        stored = ("true" if value else "false") if isinstance(value, bool) else str(value)
        db.merge(Setting(key=key, value=stored))
    db.commit()
    return read_settings(db)


@router.get("/catalog")
def get_catalog():
    """Listas cerradas para los selectores del frontend."""
    return catalog.as_dict()
