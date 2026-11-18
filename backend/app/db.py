from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config


class Base(DeclarativeBase):
    pass


config.ensure_dirs()
engine = create_engine(f"sqlite:///{config.DB_PATH}", connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    from . import models  # noqa: F401  (registra las tablas)

    Base.metadata.create_all(engine)
    _add_missing_columns()


# Columnas añadidas después de la primera versión. create_all no toca tablas que ya existen,
# así que se añaden a mano para que actualizar la app no pierda datos.
_NEW_COLUMNS = {
    "garments": {
        "ai_draft": "JSON",
        "photo_label": "VARCHAR(32)",
        "photo_label_original": "VARCHAR(64)",
        "photo_extra": "VARCHAR(32)",
        "photo_extra_original": "VARCHAR(64)",
        "closure": "VARCHAR(20)",
        "ai_model": "VARCHAR(60)",
        "hood": "BOOLEAN",
        "fit": "VARCHAR(20)",
        "thickness": "VARCHAR(20)",
        "reference": "VARCHAR(40)",
        "store_name": "VARCHAR(40)",
        "store_url": "TEXT",
        "on_order": "BOOLEAN",
        "ordered_at": "DATETIME",
        "photos_camera": "JSON",
    },
    "wear_log": {"outfit_id": "INTEGER"},
    "ratings": {"culprit_ids": "JSON"},
    "shop_items": {
        "decided_at": "DATETIME", "can_undo": "BOOLEAN", "discard_reason": "VARCHAR(20)",
        "prev_status": "VARCHAR(20)", "siblings": "JSON", "composition": "TEXT",
        "brand": "VARCHAR(40)", "name_es": "VARCHAR(160)", "store_color_es": "VARCHAR(60)",
        "composition_es": "TEXT", "translated": "BOOLEAN", "listed_at": "DATETIME",
        "maker_code": "VARCHAR(40)",
    },
}


def _add_missing_columns() -> None:
    with engine.begin() as conn:
        for table, columns in _NEW_COLUMNS.items():
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            if not existing:  # la tabla no existe: create_all la crea ya completa
                continue
            for name, sql_type in columns.items():
                if name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
