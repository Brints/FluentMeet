"""FastAPI dependencies for the user feature package."""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.user.service import UserService


def get_user_service(
    db: Session = Depends(get_db),
) -> UserService:
    """Provide a ``UserService`` wired to the current request's DB session.

    Args:
        db (Session): Database transaction manager natively injected.
            Defaults to `get_db`.

    Returns:
        UserService: Service entity bound to logic boundaries.
    """
    return UserService(db=db)
