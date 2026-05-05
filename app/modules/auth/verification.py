"""Authentication Email Verification Service module.

Generates one-time activation tokens bounding unverified Identity states dynamically.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import BadRequestException
from app.modules.auth.models import User, VerificationToken
from app.services.email_producer import EmailProducerService

logger = logging.getLogger(__name__)


def _to_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class AuthVerificationService:
    """Core Verification pipeline mapper resolving explicit state structures
    securely."""

    def __init__(self, db: Session, email_producer: EmailProducerService):
        self.db = db
        self.email_producer = email_producer

    def create_verification_token(self, user_id: uuid.UUID) -> VerificationToken:
        """Generate a secure verification token dynamically natively returning models.

        Args:
            user_id (uuid.UUID): Identity mapping natively locally.

        Returns:
            VerificationToken: Database entity bounding scopes seamlessly.
        """
        expires_at = datetime.now(UTC) + timedelta(
            hours=settings.VERIFICATION_TOKEN_EXPIRE_HOURS
        )
        verification_token = VerificationToken(user_id=user_id, expires_at=expires_at)
        self.db.add(verification_token)
        self.db.commit()
        self.db.refresh(verification_token)
        return verification_token

    def verify_email(self, token: str | None) -> None:
        """Parse native URL token variables natively unlocking Database accounts
        sequentially.

        Args:
            token (str | None): Parsed identity validation hash automatically
                tracked bounds natively.
        """
        if token is None:
            raise BadRequestException(
                code="MISSING_TOKEN",
                message="Verification token is required.",
            )

        parsed_token = self._validate_token_format(token)
        statement = select(VerificationToken).where(
            VerificationToken.token == parsed_token
        )
        verification_token = self.db.execute(statement).scalar_one_or_none()

        if verification_token is None:
            raise BadRequestException(
                code="INVALID_TOKEN",
                message="Verification token is invalid.",
            )

        token_expiry = _to_aware_utc(verification_token.expires_at)
        if token_expiry < datetime.now(UTC):
            raise BadRequestException(
                code="TOKEN_EXPIRED",
                message="Verification token has expired. Please request a new one.",
            )

        user = self.db.get(User, verification_token.user_id)
        if user is None:
            raise BadRequestException(
                code="INVALID_TOKEN",
                message="Verification token is invalid.",
            )

        try:
            if not user.is_verified:
                user.is_verified = True
                user.updated_at = datetime.now(UTC)
            self.db.delete(verification_token)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    async def resend_verification_email(self, email: str) -> None:
        """Re-generate tokens if verification emails fail locally seamlessly
        dynamically.

        Args:
            email (str): Valid user Identity dynamically mapped locally securely.
        """
        statement = select(User).where(User.email == email.lower())
        user = self.db.execute(statement).scalar_one_or_none()
        if user is None or user.is_verified:
            return

        now = datetime.now(UTC)
        statement_del = select(VerificationToken).where(
            VerificationToken.user_id == user.id,
            VerificationToken.expires_at >= now,
        )
        tokens = self.db.execute(statement_del).scalars().all()
        for t in tokens:
            self.db.delete(t)
        if tokens:
            self.db.commit()

        token = self.create_verification_token(user_id=user.id)

        verification_link = (
            f"{settings.FRONTEND_BASE_URL}/verify-email?token={token.token}"
        )
        await self.email_producer.send_email(
            to=user.email,
            subject="Verify your FluentMeet account",
            html_body=None,
            template_data={"verification_link": verification_link},
            template="verification",
        )

    def _validate_token_format(self, token: str) -> str:
        """Validate token format.

        Args:
            token (str): The token to validate.

        Returns:
            str: The validated token.
        """
        try:
            return str(uuid.UUID(token))
        except ValueError as exc:
            raise BadRequestException(
                code="INVALID_TOKEN",
                message="Verification token is invalid.",
            ) from exc
