from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import catalog
from ..db import get_db
from ..models import Setting
from ..schemas import AIStatus, CodexLogin, CodexUsage, SettingsOut, SettingsUpdate
from ..services.ai import codex_login, codex_models, codex_usage
from ..services.ai import claude as claude_ai
from ..services.ai.selector import ANALYZERS

router = APIRouter(prefix="/api", tags=["ajustes"])

DEFAULTS = {
    "theme": "sistema",
    "ai_provider": "codex",
    "codex_model": "",
    "codex_effort": "",
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
        codex_model=values["codex_model"],
        codex_effort=values["codex_effort"],
        city=values["city"],
        notify_enabled=values["notify_enabled"] == "true",
        notify_time=values["notify_time"],
    )


@router.get("/settings", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db)):
    return read_settings(db)


@router.patch("/settings", response_model=SettingsOut)
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db)):
    changes = body.model_dump(exclude_none=True)
    api_key = changes.pop("anthropic_api_key", None)
    if api_key is not None:  # se guarda aparte y nunca se devuelve
        api_key = api_key.strip()
        if api_key:
            db.merge(Setting(key=claude_ai.API_KEY_SETTING, value=api_key))
        else:
            db.query(Setting).filter(Setting.key == claude_ai.API_KEY_SETTING).delete()
    for key, value in changes.items():
        stored = ("true" if value else "false") if isinstance(value, bool) else str(value)
        db.merge(Setting(key=key, value=stored))
    db.commit()
    return read_settings(db)


@router.get("/ai/status", response_model=AIStatus)
def ai_status():
    """Qué proveedores están listos, para que Ajustes lo muestre. No devuelve ninguna clave."""
    codex = ANALYZERS["codex"]
    return AIStatus(
        codex_installed=codex.available(),
        codex_logged_in=codex.available() and codex.logged_in(),
        claude_configured=claude_ai.api_key() is not None,
    )


@router.post("/ai/codex/login", response_model=CodexLogin)
def codex_login_start():
    """Empieza el inicio de sesión de Codex: devuelve el enlace y el código que hay que introducir."""
    try:
        return codex_login.start()
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get("/ai/codex/login", response_model=CodexLogin)
def codex_login_status():
    return codex_login.status()


@router.delete("/ai/codex/login", status_code=204)
def codex_login_cancel():
    codex_login.cancel()


@router.post("/ai/codex/logout", response_model=AIStatus)
def codex_logout():
    try:
        codex_login.logout()
        codex_usage.forget()
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    return ai_status()


@router.get("/ai/codex/models")
def codex_models_list():
    """Modelos que Codex ofrece a esta cuenta (de su propia caché) y los esfuerzos que se pueden elegir."""
    return {"models": codex_models.available(), "efforts": list(codex_models.EFFORTS)}


@router.get("/ai/codex/usage", response_model=CodexUsage)
def codex_usage_read():
    """Cuánto límite de Codex queda en la cuenta (ventana de 5 horas y semanal)."""
    try:
        return codex_usage.read()
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get("/catalog")
def get_catalog():
    """Listas cerradas para los selectores del frontend."""
    return catalog.as_dict()
