"""Authentication core business service module.

Coordinates transactional databases natively orchestrating OAuth triggers dynamically.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    UnauthorizedException,
)
from app.core.sanitize import sanitize_log_args
from app.core.security import SecurityService
from app.modules.auth.account_lockout import AccountLockoutService
from app.modules.auth.models import PasswordResetToken, User
from app.modules.auth.schemas import (
    LoginRequest,
    LoginResponse,
    RefreshTokenResponse,
    SignupRequest,
)
from app.modules.auth.token_store import TokenStoreService
from app.modules.auth.verification import AuthVerificationService
from app.services.email_producer import EmailProducerService

logger = logging.getLogger(__name__)


class AuthService:
    """Core Authentication pipeline mapper resolving explicit state structures."""

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
        """Query User explicitly targeting lowercased email bindings constraints.

        Args:
            email (str): Target search payload.

        Returns:
            User | None: Retrieved structure natively.
        """
        statement = select(User).where(User.email == email.lower())
        return self.db.execute(statement).scalar_one_or_none()

    async def signup(self, user_in: SignupRequest, frontend_base_url: str) -> User:
        """Register a new native participant.

        Args:
            user_in (SignupRequest): Target parameter mappings array natively.
            frontend_base_url (str): The frontend UI router domain natively targeting Verification links.

        Returns:
            User: Explicitly constructed account struct mapped.
        """
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

    async def _handle_failed_login(self, email: str) -> None:
        """Process a failed login attempt, throwing precise locked or invalid exceptions.

        Args:
            email (str): Target user email identifier.

        Raises:
            ForbiddenException: Configured with `ACCOUNT_LOCKED` code and `lock_time_left` metadata.
            UnauthorizedException: Configured with `INVALID_CREDENTIALS` code and `attempts_remaining` metadata.
        """
        await self.lockout_svc.record_failed_attempt(email)
        lockout_info = await self.lockout_svc.get_lockout_info(email)

        if lockout_info.get("is_locked"):
            raise ForbiddenException(
                code="ACCOUNT_LOCKED",
                message="Account is temporarily locked due to too many failed login attempts.",
                details=[{"lock_time_left": lockout_info.get("lock_time_left")}],
            )

        attempts = lockout_info.get("attempts_remaining", 0)
        raise UnauthorizedException(
            code="INVALID_CREDENTIALS",
            message="Invalid email or password.",
            details=[{"attempts_remaining": attempts}],
        )

    async def login(self, payload: LoginRequest) -> tuple[LoginResponse, str, int]:
        """Verify explicit payload credentials against databases generating state sessions securely.

        Args:
            payload (LoginRequest): Incoming frontend request struct containing user parameters.

        Returns:
            tuple[LoginResponse, str, int]: Issued explicit token dicts, the raw RT string natively, and TTL in seconds.

        Raises:
            ForbiddenException: If account is locked (returns details metadata with `lock_time_left`).
            UnauthorizedException: If email/password are incorrect (returns details metadata with `attempts_remaining`).
        """
        email = payload.email.lower()

        # Check lockout
        lockout_info = await self.lockout_svc.get_lockout_info(email)
        if lockout_info.get("is_locked"):
            raise ForbiddenException(
                code="ACCOUNT_LOCKED",
                message="Account is temporarily locked due to too many failed login attempts.",
                details=[{"lock_time_left": lockout_info.get("lock_time_left")}],
            )

        # Lookup user
        user = self.get_user_by_email(email)
        if user is None:
            await self._handle_failed_login(email)

        # Verify password
        if not self.security_service.verify_password(
            payload.password, user.hashed_password
        ):
            await self._handle_failed_login(email)

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
        """Handle forgot password request.

        Args:
            email (str): Target email address.
            frontend_base_url (str): The frontend UI router domain natively targeting Verification links.

        Returns:
            None
        """
        user = self.get_user_by_email(email)
        if (
            not user
            or not user.is_active
            or user.deleted_at is not None
            or not user.is_verified
        ):
            return

        # Delete existing tokens for this user
        existing_tokens = self.db.scalars(
            select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
        ).all()
        for token in existing_tokens:
            self.db.delete(token)

        # Create new token
        expires_at = datetime.now(UTC) + timedelta(
            minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
        )
        reset_token = PasswordResetToken(user_id=user.id, expires_at=expires_at)
        self.db.add(reset_token)
        self.db.commit()
        self.db.refresh(reset_token)

        reset_link = f"{frontend_base_url}/reset-password?token={reset_token.token}"
        try:
            await self.email_producer.send_email(
                to=user.email,
                subject="Reset your FluentMeet password",
                html_body=None,
                template_data={
                    "full_name": user.full_name or "User",
                    "reset_link": reset_link,
                    "expires_in_minutes": settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES,
                },
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
        """Handle token refresh request.

        Args:
            raw_token (str): The raw refresh token.

        Returns:
            tuple[RefreshTokenResponse, str, int]: The new access token, refresh token, and TTL in seconds.
        """
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

    async def resolve_oauth_user(
        self, email: str, google_id: str, name: str | None, avatar_url: str | None
    ) -> tuple[LoginResponse, str, int]:
        """Handle OAuth user resolution.

        Args:
            email (str): Target email address.
            google_id (str): The Google ID.
            name (str | None): The user's name.
            avatar_url (str | None): The user's avatar URL.

        Returns:
            tuple[LoginResponse, str, int]: The new access token, refresh token, and TTL in seconds.
        """
        email = email.lower()
        user = self.get_user_by_email(email)

        if user:
            # Check lockout
            if await self.lockout_svc.is_locked(email):
                raise ForbiddenException(
                    code="ACCOUNT_LOCKED",
                    message="Account is temporarily locked. Please try again later.",
                )

            # Verify if user is active
            if user.deleted_at is not None or not user.is_active:
                raise ForbiddenException(
                    code="ACCOUNT_DEACTIVATED",
                    message="This account has been deactivated or deleted.",
                )

            # Link account if not linked
            if not user.google_id:
                user.google_id = google_id
            if not user.avatar_url and avatar_url:
                user.avatar_url = avatar_url
            if not user.is_verified:
                user.is_verified = True

            self.db.commit()
            self.db.refresh(user)
        else:
            # Create new user
            random_password = str(uuid.uuid4())
            user = User(
                email=email,
                hashed_password=self.security_service.hash_password(random_password),
                full_name=name,
                avatar_url=avatar_url,
                google_id=google_id,
                is_active=True,
                is_verified=True,
            )
            self.db.add(user)
            self.db.commit()
            self.db.refresh(user)

        # Issue tokens for successful OAuth login
        access_token, expires_in = self.security_service.create_access_token(
            email=email
        )
        refresh_token, refresh_jti, refresh_ttl = (
            self.security_service.create_refresh_token(email=email)
        )

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

    # ------------------------------------------------------------------
    # Logout
    # ------------------------------------------------------------------

    async def logout(
        self,
        email: str,
        access_jti: str,
        access_ttl_remaining: int,
        refresh_jti: str | None,
    ) -> None:
        """Invalidate the current session.

        Blacklists the access-token JTI so that ``get_current_user``
        rejects it on subsequent requests, and revokes the refresh-token
        JTI (if provided) so it cannot be rotated again.
        """
        await self.token_store.blacklist_access_token(
            jti=access_jti, ttl_seconds=access_ttl_remaining
        )

        if refresh_jti:
            await self.token_store.revoke_refresh_token(email=email, jti=refresh_jti)

    # ------------------------------------------------------------------
    # Reset Password (unauthenticated — uses email token)
    # ------------------------------------------------------------------

    async def reset_password(self, token: str, new_password: str) -> None:
        """Validate a password-reset token and apply the new password.

        Args:
            token (str): The password reset token.
            new_password (str): The new password.

        Returns:
            None
        """
        reset_token = self.db.execute(
            select(PasswordResetToken).where(PasswordResetToken.token == token)
        ).scalar_one_or_none()

        if reset_token is None:
            raise BadRequestException(
                code="INVALID_RESET_TOKEN",
                message="Password reset token is invalid.",
            )

        if reset_token.expires_at.tzinfo is None:
            expires_at = reset_token.expires_at.replace(tzinfo=UTC)
        else:
            expires_at = reset_token.expires_at

        if expires_at < datetime.now(UTC):
            raise BadRequestException(
                code="RESET_TOKEN_EXPIRED",
                message=("Password reset token has expired. Please request a new one."),
            )

        user = self.db.execute(
            select(User).where(User.id == reset_token.user_id)
        ).scalar_one_or_none()

        if user is None:  # pragma: no cover — defensive
            raise BadRequestException(
                code="INVALID_RESET_TOKEN",
                message="Password reset token is invalid.",
            )

        # Reject if new password matches the current one
        if self.security_service.verify_password(new_password, user.hashed_password):
            raise BadRequestException(
                code="SAME_PASSWORD",
                message="New password must be different from the current password.",
            )

        # Atomic DB update
        user.hashed_password = self.security_service.hash_password(new_password)
        user.updated_at = datetime.now(UTC)
        self.db.delete(reset_token)
        self.db.commit()

        # Revoke all sessions — best-effort (password is already changed)
        try:
            await self.token_store.revoke_all_user_tokens(email=user.email)
        except Exception as exc:
            email_safe, exc_safe = sanitize_log_args(user.email, exc)
            logger.warning(
                "Failed to revoke sessions for %s after password reset: %s",
                email_safe,
                exc_safe,
            )

        # Send security notification email
        try:
            await self.email_producer.send_email(
                to=user.email,
                subject="Your FluentMeet password was reset",
                html_body=None,
                template_data={
                    "full_name": user.full_name or "User",
                },
                template="password_changed",
            )
        except Exception as exc:
            email_safe, exc_safe = sanitize_log_args(user.email, exc)
            logger.warning(
                "Failed to send password-reset confirmation for %s: %s",
                email_safe,
                exc_safe,
            )

    # ------------------------------------------------------------------
    # Change Password (authenticated)
    # ------------------------------------------------------------------

    async def change_password(
        self, user: User, current_password: str, new_password: str
    ) -> None:
        """Change the password for an authenticated user.

        Args:
            user (User): The authenticated user.
            current_password (str): The current password.
            new_password (str): The new password.

        Returns:
            None
        """
        if not self.security_service.verify_password(
            current_password, user.hashed_password
        ):
            raise BadRequestException(
                code="INCORRECT_PASSWORD",
                message="Current password is incorrect.",
            )

        if current_password == new_password:
            raise BadRequestException(
                code="SAME_PASSWORD",
                message="New password must be different from the current password.",
            )

        # Atomic DB update
        user.hashed_password = self.security_service.hash_password(new_password)
        user.updated_at = datetime.now(UTC)
        self.db.commit()

        # Revoke all refresh tokens — best-effort
        try:
            await self.token_store.revoke_all_user_tokens(email=user.email)
        except Exception as exc:
            email_safe, exc_safe = sanitize_log_args(user.email, exc)
            logger.warning(
                "Failed to revoke sessions for %s after password change: %s",
                email_safe,
                exc_safe,
            )

        # Send security notification email
        try:
            await self.email_producer.send_email(
                to=user.email,
                subject="Your FluentMeet password was changed",
                html_body=None,
                template_data={
                    "full_name": user.full_name or "User",
                },
                template="password_changed",
            )
        except Exception as exc:
            email_safe, exc_safe = sanitize_log_args(user.email, exc)
            logger.warning(
                "Failed to send password-change confirmation for %s: %s",
                email_safe,
                exc_safe,
            )
