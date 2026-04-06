"""User CRUD service layer.

All database mutations for user-profile management live here,
keeping the router thin and the logic testable in isolation.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth.models import User, VerificationToken
from app.core.sanitize import sanitize_for_log

logger = logging.getLogger(__name__)


class UserService:
    """Encapsulates user-profile CRUD operations."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_user_by_id(self, user_id: uuid.UUID) -> User | None:
        """Return the user with *user_id*, or ``None``."""
        return self.db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update_user(self, user: User, update_data: dict) -> User:
        """Apply a partial update to *user* using only the provided fields.

        Args:
            user: The ORM instance to update.
            update_data: A ``dict`` whose keys are User column names.
                         Only non-``None`` values are written.

        Returns:
            The refreshed ``User`` instance.
        """
        for field, value in update_data.items():
            if value is not None:
                setattr(user, field, value)

        user.updated_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(user)
        return user

    def update_avatar_url(self, user: User, avatar_url: str) -> User:
        """Set the avatar URL on *user* and persist.

        Returns:
            The refreshed ``User`` instance.
        """
        user.avatar_url = avatar_url
        user.updated_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(user)
        return user

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def soft_delete_user(self, user: User) -> None:
        """Mark *user* as deleted without removing the DB row.

        Sets ``deleted_at`` to the current UTC timestamp and
        ``is_active`` to ``False``.
        """
        user.deleted_at = datetime.now(UTC)
        user.is_active = False
        user.updated_at = datetime.now(UTC)
        self.db.commit()
        logger.info(
            "Soft-deleted user %s",
            sanitize_for_log(str(user.id)),
        )

    def hard_delete_user(self, user: User) -> None:
        """Permanently remove *user* and all associated records.

        Cascading deletes:
        - Verification tokens linked to the user.
        - The user row itself.
        """
        user_id = user.id

        # Delete associated verification tokens first.
        self.db.execute(delete(VerificationToken).where(VerificationToken.user_id == user_id))

        self.db.delete(user)
        self.db.commit()
        logger.info(
            "Hard-deleted user %s and associated records",
            sanitize_for_log(str(user_id)),
        )
