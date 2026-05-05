"""SQLAlchemy foundational declarative base.

This module provides the core `Base` metadata class used by all domain
models within the FluentMeet application. By centralizing the
DeclarativeBase here, we prevent circular import issues when different
module packages need to define relational schemas.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """The central SQLAlchemy 2.0 declarative base registry.

    All ORM models across the application must inherit from this class
    to ensure their metadata is properly registered for Alembic
    auto-migrations and query building.
    """

    pass
