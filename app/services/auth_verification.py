import uuid
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import BadRequestException
from app.crud.user.user import get_user_by_email
from app.crud.verification_token import (
    VerificationTokenRepository,
    verification_token_repository,
)
from app.models.user import User
from app.models.verification_token import VerificationToken
from app.services.email_producer import EmailProducerService


def _to_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class AuthVerificationService:
    def __init__(
        self,
        token_repository: VerificationTokenRepository = verification_token_repository,
    ) -> None:
        self._token_repository: Final[VerificationTokenRepository] = token_repository

    def create_verification_token(
        self, db: Session, user_id: uuid.UUID
    ) -> VerificationToken:
        return self._token_repository.create_token(db=db, user_id=user_id)

    def verify_email(self, db: Session, token: str | None) -> None:
        if token is None:
            raise BadRequestException(
                code="MISSING_TOKEN",
                message="Verification token is required.",
            )

        parsed_token = self._validate_token_format(token)
        verification_token = self._token_repository.get_token(
            db=db,
            token=parsed_token,
        )
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

        user = db.get(User, verification_token.user_id)
        if user is None:
            raise BadRequestException(
                code="INVALID_TOKEN",
                message="Verification token is invalid.",
            )

        try:
            if not user.is_verified:
                user.is_verified = True
                user.updated_at = datetime.now(UTC)
            db.delete(verification_token)
            db.commit()
        except Exception:
            db.rollback()
            raise

    async def resend_verification_email(
        self,
        db: Session,
        email: str,
        email_producer: EmailProducerService,
    ) -> None:
        user = get_user_by_email(db, email)
        if user is None or user.is_verified:
            return

        self._token_repository.delete_unexpired_tokens_for_user(db=db, user_id=user.id)
        token = self._token_repository.create_token(db=db, user_id=user.id)

        verification_link = (
            f"{settings.FRONTEND_BASE_URL}/verify-email?token={token.token}"
        )
        await email_producer.send_email(
            to=user.email,
            subject="Verify your FluentMeet account",
            html_body=None,
            template_data={"verification_link": verification_link},
            template="verification",
        )

    def _validate_token_format(self, token: str) -> str:
        try:
            return str(UUID(token))
        except ValueError as exc:
            raise BadRequestException(
                code="INVALID_TOKEN",
                message="Verification token is invalid.",
            ) from exc


auth_verification_service = AuthVerificationService()


def get_auth_verification_service() -> AuthVerificationService:
    return auth_verification_service
