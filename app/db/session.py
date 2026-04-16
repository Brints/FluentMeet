"""Database session configuration module.

This module provides the central SQLAlchemy `Engine` and `Session` generator
management layer required to interact with relational state securely across the app.
"""

import logging
from collections.abc import Generator
from typing import Final

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

logger = logging.getLogger(__name__)

DEFAULT_SQLITE_URL: Final[str] = "sqlite:///./fluentmeet.db"


def _coerce_sync_url(url: str) -> str:
    """Replace the async ``asyncpg`` driver with sync ``psycopg2``.

    The application uses synchronous SQLAlchemy (``create_engine`` +
    ``Session``), so the ``asyncpg`` DBAPI - which requires
    ``create_async_engine`` - will fail at runtime with a
    ``MissingGreenlet`` error. This helper silently swaps the driver
    so that the connection string from ``.env`` works out of the box.

    Args:
        url (str): The raw database URL parsed from settings.

    Returns:
        str: The coerced synchronous-compatible database URL.
    """
    if "+asyncpg" in url:
        fixed = url.replace("+asyncpg", "+psycopg2")
        logger.info(
            "Replaced async driver 'asyncpg' with sync"
            " driver 'psycopg2' in DATABASE_URL."
        )
        return fixed
    return url


DATABASE_URL = (
    _coerce_sync_url(settings.DATABASE_URL)
    if settings.DATABASE_URL
    else DEFAULT_SQLITE_URL
)

_ENGINE_STATE: dict[str, Engine] = {}
SessionLocal = sessionmaker(autoflush=False, autocommit=False)


def get_engine() -> Engine:
    """Instantiate or return the globally cached SQLAlchemy DB Engine.

    Dynamically provisions an Engine utilizing connection pooling and
    pre-ping configurations. Will auto-fallback to an SQLite database
    string if Postgres python drivers are not present (for CI/Test harnesses).

    Returns:
        Engine: The lazily evaluated global SQLAlchemy core Engine.
    """
    cached_engine = _ENGINE_STATE.get("engine")
    if cached_engine is None:
        try:
            cached_engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        except ModuleNotFoundError as exc:
            # CI/test environments may not install PostgreSQL DBAPI drivers.
            if DATABASE_URL.startswith("postgresql") and exc.name in {
                "psycopg2",
                "psycopg",
                "asyncpg",
            }:
                cached_engine = create_engine(DEFAULT_SQLITE_URL, pool_pre_ping=True)
            else:
                raise
        SessionLocal.configure(bind=cached_engine)
        _ENGINE_STATE["engine"] = cached_engine
    return cached_engine


def get_db() -> Generator[Session, None, None]:
    """Provide a transactional DB session for FastAPI dependencies.

    Yields a standard `Session` boundary managed by a `finally` closer logic.
    Forces auto-boot of the engine context.

    Yields:
        Session: Active database query context session.
    """
    get_engine()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
