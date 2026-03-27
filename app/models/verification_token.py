import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.user import Base


def default_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(hours=24)


class VerificationToken(Base):
    """Model representing a verification token for email verification or password reset.

    Attributes:
        id (int): Primary key identifier for the token.
        user_id (uuid.UUID): Foreign key referencing the associated user.
        token (str): Unique token string used for verification.
        expires_at (datetime): Timestamp indicating when the token expires.
        created_at (datetime): Timestamp indicating when the token was created.
    """

    __tablename__ = "verification_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    token: Mapped[str] = mapped_column(
        String(36),
        unique=True,
        index=True,
        nullable=False,
        default=lambda: str(uuid.uuid4()),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=default_expiry
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
