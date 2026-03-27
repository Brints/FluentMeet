"""Security utilities for password hashing and JWT token management."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import bcrypt
from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings


class SecurityService:
    """Centralised service for password operations and JWT token creation.

    Attributes:
        pwd_context: passlib CryptContext configured for bcrypt hashing.
    """

    def __init__(self) -> None:
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    # ------------------------------------------------------------------
    # Password helpers
    # ------------------------------------------------------------------

    def hash_password(self, password: str) -> str:
        """Hash *password* using bcrypt.

        Falls back to raw ``bcrypt`` if passlib's backend probing fails
        (common with newer bcrypt builds).
        """
        try:
            return cast(str, self.pwd_context.hash(password))
        except ValueError:
            salt = bcrypt.gensalt()
            return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Return ``True`` when *plain_password* matches *hashed_password*.

        Falls back to raw ``bcrypt.checkpw`` when passlib's backend
        probing fails (same compatibility issue as :meth:`hash_password`).
        """
        try:
            return bool(self.pwd_context.verify(plain_password, hashed_password))
        except (ValueError, TypeError, AttributeError):
            try:
                return bcrypt.checkpw(
                    plain_password.encode("utf-8"),
                    hashed_password.encode("utf-8"),
                )
            except Exception:
                return False

    # ------------------------------------------------------------------
    # JWT helpers
    # ------------------------------------------------------------------

    def create_access_token(
        self,
        email: str,
        jti: str | None = None,
    ) -> tuple[str, int]:
        """Create a short-lived JWT access token.

        Returns:
            A ``(token, expires_in_seconds)`` tuple.
        """
        jti = jti or str(uuid4())
        expires_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        expire = datetime.now(UTC) + expires_delta

        payload: dict[str, Any] = {
            "sub": email,
            "jti": jti,
            "exp": expire,
            "type": "access",
        }
        token = jwt.encode(
            payload,
            settings.SECRET_KEY,
            algorithm=settings.ALGORITHM,
        )
        return token, int(expires_delta.total_seconds())

    def create_refresh_token(
        self,
        email: str,
        jti: str | None = None,
    ) -> tuple[str, str, int]:
        """Create a long-lived JWT refresh token.

        Returns:
            A ``(token, jti, ttl_seconds)`` tuple.
        """
        jti = jti or str(uuid4())
        ttl_seconds = settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400
        expire = datetime.now(UTC) + timedelta(seconds=ttl_seconds)

        payload: dict[str, Any] = {
            "sub": email,
            "jti": jti,
            "exp": expire,
            "type": "refresh",
        }
        token = jwt.encode(
            payload,
            settings.SECRET_KEY,
            algorithm=settings.ALGORITHM,
        )
        return token, jti, ttl_seconds


# Module-level singleton -----------------------------------------------
security_service = SecurityService()


def get_security_service() -> SecurityService:
    """FastAPI dependency that returns the module-level SecurityService."""
    return security_service
