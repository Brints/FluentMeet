from app.models.user import Base, User # noqa

# Export all models for Alembic
__all__ = ["Base", "User"]
