"""Redis-backed account-lockout service.

Tracks consecutive failed login attempts per email address and
locks the account for a configurable period once the threshold is
reached.

Redis keys
----------
``login_attempts:{email}``  - integer counter, no TTL (cleared on success).
``account_locked:{email}``  - flag (value ``"1"``), TTL = lockout period.
"""

import logging

import redis.asyncio as aioredis

from app.core.config import settings
from app.core.sanitize import sanitize_log_args

logger = logging.getLogger(__name__)

_REDIS_CLIENT: aioredis.Redis | None = None


def _get_redis_client() -> aioredis.Redis:
    """Return (and lazily create) a module-level async Redis client."""
    global _REDIS_CLIENT  # noqa: PLW0603
    if _REDIS_CLIENT is None:
        _REDIS_CLIENT = aioredis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            decode_responses=True,
        )
    return _REDIS_CLIENT


class AccountLockoutService:
    """Enforces an account-lockout policy based on consecutive failures.

    After ``MAX_FAILED_LOGIN_ATTEMPTS`` wrong-password attempts on the
    same email address, the account is locked for
    ``ACCOUNT_LOCKOUT_DAYS`` days.  A successful login resets the
    failure counter.
    """

    ATTEMPTS_PREFIX = "login_attempts"
    LOCKED_PREFIX = "account_locked"

    def __init__(self, redis_client: aioredis.Redis | None = None) -> None:
        self._redis = redis_client or _get_redis_client()
        self._max_attempts = settings.MAX_FAILED_LOGIN_ATTEMPTS
        self._lockout_ttl = settings.ACCOUNT_LOCKOUT_DAYS * 86400

    # ------------------------------------------------------------------
    # Key helpers
    # ------------------------------------------------------------------

    def _attempts_key(self, email: str) -> str:
        return f"{self.ATTEMPTS_PREFIX}:{email}"

    def _locked_key(self, email: str) -> str:
        return f"{self.LOCKED_PREFIX}:{email}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def is_locked(self, email: str) -> bool:
        """Return ``True`` if the account for *email* is currently locked."""
        return bool(await self._redis.exists(self._locked_key(email)))

    async def record_failed_attempt(self, email: str) -> None:
        """Increment the failure counter and lock the account if threshold reached."""
        attempts_key = self._attempts_key(email)
        count = await self._redis.incr(attempts_key)

        if count >= self._max_attempts:
            # Lock the account and clear the counter.
            await self._redis.set(
                self._locked_key(email),
                "1",
                ex=self._lockout_ttl,
            )
            await self._redis.delete(attempts_key)
            logger.warning(
                "Account locked for %s after %d failed attempts",
                sanitize_log_args(email),
                count,
            )

    async def reset_attempts(self, email: str) -> None:
        """Clear the failure counter (called on successful login)."""
        await self._redis.delete(self._attempts_key(email))


# Module-level singleton -----------------------------------------------
account_lockout_service = AccountLockoutService()


def get_account_lockout_service() -> AccountLockoutService:
    """FastAPI dependency returning the module-level AccountLockoutService."""
    return account_lockout_service
