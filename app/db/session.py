from collections.abc import Generator
from typing import Final

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

DEFAULT_SQLITE_URL: Final[str] = "sqlite:///./fluentmeet.db"
DATABASE_URL = settings.DATABASE_URL or DEFAULT_SQLITE_URL

_ENGINE_STATE: dict[str, Engine] = {}
SessionLocal = sessionmaker(autoflush=False, autocommit=False)


def get_engine() -> Engine:
    cached_engine = _ENGINE_STATE.get("engine")
    if cached_engine is None:
        try:
            cached_engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        except ModuleNotFoundError as exc:
            # CI/test environments may not install PostgreSQL DBAPI drivers.
            if DATABASE_URL.startswith("postgresql") and exc.name in {
                "psycopg2",
                "psycopg",
            }:
                cached_engine = create_engine(DEFAULT_SQLITE_URL, pool_pre_ping=True)
            else:
                raise
        SessionLocal.configure(bind=cached_engine)
        _ENGINE_STATE["engine"] = cached_engine
    return cached_engine


def get_db() -> Generator[Session, None, None]:
    get_engine()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
