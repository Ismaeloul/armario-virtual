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


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
