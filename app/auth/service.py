import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.account_lockout import AccountLockoutService
from app.auth.models import User
from app.auth.schemas import (
    LoginRequest,
    LoginResponse,
    RefreshTokenResponse,
    SignupRequest,
)
from app.auth.token_store import TokenStoreService
from app.auth.verification import AuthVerificationService
from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    UnauthorizedException,
)
from app.core.sanitize import sanitize_log_args
from app.core.security import SecurityService
from app.services.email_producer import EmailProducerService

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(
        self,
        db: Session,
        security_service: SecurityService,
        email_producer: EmailProducerService,
        auth_verification_service: AuthVerificationService,
        lockout_svc: AccountLockoutService,
        token_store: TokenStoreService,
    ):
        self.db = db
        self.security_service = security_service
        self.email_producer = email_producer
        self.auth_verification_service = auth_verification_service
        self.lockout_svc = lockout_svc
        self.token_store = token_store

    def get_user_by_email(self, email: str) -> User | None:
        statement = select(User).where(User.email == email.lower())
        return self.db.execute(statement).scalar_one_or_none()

    async def signup(self, user_in: SignupRequest, frontend_base_url: str) -> User:
        existing_user = self.get_user_by_email(user_in.email)
        if existing_user:
            raise ConflictException(
                code="EMAIL_ALREADY_REGISTERED",
                message="An account with this email already exists.",
            )

        db_user = User(
            email=user_in.email.lower(),
            hashed_password=self.security_service.hash_password(user_in.password),
            full_name=user_in.full_name,
            speaking_language=user_in.speaking_language.value,
            listening_language=user_in.listening_language.value,
            is_active=True,
            is_verified=False,
        )
        self.db.add(db_user)
        self.db.commit()
        self.db.refresh(db_user)

        verification_token = self.auth_verification_service.create_verification_token(
            user_id=db_user.id,
        )

        verification_link = (
            f"{frontend_base_url}/verify-email?token={verification_token.token}"
        )

        try:
            await self.email_producer.send_email(
                to=db_user.email,
                subject="Verify your FluentMeet account",
                html_body=None,
                template_data={"verification_link": verification_link},
                template="verification",
            )
        except Exception as exc:
            user_id_safe, exc_safe = sanitize_log_args(db_user.id, exc)
            logger.warning(
                "Failed to enqueue verification email for user %s: %s",
                user_id_safe,
                exc_safe,
            )

        return db_user

    async def login(self, payload: LoginRequest) -> tuple[LoginResponse, str, int]:
        email = payload.email.lower()

        # Check lockout
        if await self.lockout_svc.is_locked(email):
            raise ForbiddenException(
                code="ACCOUNT_LOCKED",
                message=(
                    "Account is temporarily locked due to too many failed "
                    "login attempts. Please try again later."
                ),
            )

        # Lookup user
        user = self.get_user_by_email(email)
        if user is None:
            await self.lockout_svc.record_failed_attempt(email)
            raise UnauthorizedException(
                code="INVALID_CREDENTIALS",
                message="Invalid email or password.",
            )

        # Verify password
        if not self.security_service.verify_password(
            payload.password, user.hashed_password
        ):
            await self.lockout_svc.record_failed_attempt(email)
            raise UnauthorizedException(
                code="INVALID_CREDENTIALS",
                message="Invalid email or password.",
            )

        # Guard: email verified?
        if not user.is_verified:
            raise ForbiddenException(
                code="EMAIL_NOT_VERIFIED",
                message="Please verify your email before logging in.",
            )

        # Guard: soft-deleted?
        if user.deleted_at is not None:
            raise ForbiddenException(
                code="ACCOUNT_DELETED",
                message="This account has been deleted.",
            )

        # Reset failed-login counter on success
        await self.lockout_svc.reset_attempts(email)

        # Issue tokens
        access_token, expires_in = self.security_service.create_access_token(
            email=email
        )
        refresh_token, refresh_jti, refresh_ttl = (
            self.security_service.create_refresh_token(
                email=email,
            )
        )

        # Persist refresh JTI in Redis
        await self.token_store.save_refresh_token(
            email=email, jti=refresh_jti, ttl_seconds=refresh_ttl
        )

        login_response = LoginResponse(
            access_token=access_token,
            user_id=user.id,
            token_type="bearer",
            expires_in=expires_in,
        )

        return login_response, refresh_token, refresh_ttl

    async def forgot_password(self, email: str, frontend_base_url: str) -> None:
        user = self.get_user_by_email(email)
        if not user:
            return

        reset_link = (
            f"{frontend_base_url}/reset-password?user={user.id}&token={uuid.uuid4()}"
        )
        try:
            await self.email_producer.send_email(
                to=user.email,
                subject="Reset your FluentMeet password",
                html_body=None,
                template_data={"reset_link": reset_link},
                template="password_reset",
            )
        except Exception as exc:
            email_safe, exc_safe = sanitize_log_args(user.email, exc)
            logger.warning(
                "Failed to enqueue password reset email for %s: %s",
                email_safe,
                exc_safe,
            )

    async def refresh_token(
        self, raw_token: str
    ) -> tuple[RefreshTokenResponse, str, int]:
        try:
            token_data = self.security_service.decode_refresh_token(raw_token)
        except ValueError as exc:
            raise UnauthorizedException(
                code="INVALID_REFRESH_TOKEN",
                message="Refresh token is invalid or has expired.",
            ) from exc

        email = token_data.email
        old_jti = token_data.jti

        if not await self.token_store.is_refresh_token_valid(email=email, jti=old_jti):
            await self.token_store.revoke_all_user_tokens(email=email)
            logger.warning(
                "Refresh token reuse detected for %s — all sessions revoked.",
                sanitize_log_args(email)[0],
            )
            raise UnauthorizedException(
                code="REFRESH_TOKEN_REUSE",
                message="Session has been invalidated. Please log in again.",
            )

        user = self.get_user_by_email(email)
        if user is None or user.deleted_at is not None or not user.is_active:
            raise ForbiddenException(
                code="ACCOUNT_DEACTIVATED",
                message="This account has been deactivated.",
            )

        await self.token_store.revoke_refresh_token(email=email, jti=old_jti)

        new_access_token, expires_in = self.security_service.create_access_token(
            email=email
        )
        new_refresh_token, new_jti, new_ttl = (
            self.security_service.create_refresh_token(email=email)
        )
        await self.token_store.save_refresh_token(
            email=email, jti=new_jti, ttl_seconds=new_ttl
        )

        body = RefreshTokenResponse(
            access_token=new_access_token,
            token_type="bearer",
            expires_in=expires_in,
        )

        return body, new_refresh_token, new_ttl
