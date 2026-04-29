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
from app.core.sanitize import sanitize_for_log

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
        """Initialize the AccountLockoutService.

        Args:
            redis_client (aioredis.Redis | None): Optional overriding injected Redis
                Async client. Defaults to None.
        """
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
        """Return ``True`` if the account for *email* is currently locked.

        Args:
            email (str): Target user email identifier.

        Returns:
            bool: True if account is locked, False otherwise.
        """
        return bool(await self._redis.exists(self._locked_key(email)))

    async def record_failed_attempt(self, email: str) -> None:
        """Increment the failure counter and lock the account if threshold reached.

        Args:
            email (str): Target user email identifier mapping tracking block.
        """
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
                sanitize_for_log(email),
                count,
            )

    async def reset_attempts(self, email: str) -> None:
        """Clear the failure counter (called on successful login).

        Args:
            email (str): Target user email explicitly tracking lockouts locally.
        """
        await self._redis.delete(self._attempts_key(email))

    async def get_lockout_info(self, email: str) -> dict:
        """Fetch precise lockout metadata indicating limits and remaining time.

        Args:
            email (str): Target user email identifier.

        Returns:
            dict: Lockout status containing is_locked, lock_time_left,
                and attempts_remaining.
        """
        is_locked = bool(await self._redis.exists(self._locked_key(email)))
        lock_time_left = None
        if is_locked:
            ttl_secs = await self._redis.ttl(self._locked_key(email))
            if ttl_secs > 0:
                lock_time_left = self._format_duration(ttl_secs)

        attempts_bytes = await self._redis.get(self._attempts_key(email))
        attempts = int(attempts_bytes) if attempts_bytes else 0
        attempts_remaining = max(0, self._max_attempts - attempts)

        return {
            "is_locked": is_locked,
            "lock_time_left": lock_time_left,
            "attempts_remaining": attempts_remaining,
        }

    def _format_duration(self, seconds: int) -> str:
        """Format an integer TTL into a precise human-readable duration."""
        if seconds <= 0:
            return "0 seconds"

        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds_remaining = divmod(remainder, 60)

        parts = []
        if days:
            parts.append(f"{days} day{'s' if days > 1 else ''}")
        if hours:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")

        if not parts:
            parts.append(
                f"{seconds_remaining} second{'s' if seconds_remaining > 1 else ''}"
            )

        if len(parts) == 1:
            return parts[0]
        else:
            return f"{', '.join(parts[:-1])} and {parts[-1]}"


# Module-level singleton -----------------------------------------------
account_lockout_service = AccountLockoutService()


def get_account_lockout_service() -> AccountLockoutService:
    """FastAPI dependency returning the module-level AccountLockoutService."""
    return account_lockout_service
