"""Redis-backed refresh-token persistence.

Stores refresh-token JTIs in Redis so they can be validated during
token rotation and revoked on logout.
"""

import logging

import redis.asyncio as aioredis

from app.core.config import settings

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


class TokenStoreService:
    """Manages refresh-token JTIs in Redis.

    Each stored key has the shape ``refresh_token:{jti}`` with a TTL
    that mirrors the token's own expiry, so stale entries are cleaned
    up automatically.
    """

    PREFIX = "refresh_token"

    def __init__(self, redis_client: aioredis.Redis | None = None) -> None:
        self._redis = redis_client or _get_redis_client()

    def _key(self, jti: str) -> str:
        return f"{self.PREFIX}:{jti}"

    async def save_refresh_token(self, jti: str, ttl_seconds: int) -> None:
        """Persist *jti* with an automatic expiry of *ttl_seconds*."""
        await self._redis.set(self._key(jti), "1", ex=ttl_seconds)

    async def revoke_refresh_token(self, jti: str) -> None:
        """Remove *jti*, effectively revoking the refresh token."""
        await self._redis.delete(self._key(jti))

    async def is_refresh_token_valid(self, jti: str) -> bool:
        """Return ``True`` if *jti* exists (has not been revoked/expired)."""
        return bool(await self._redis.exists(self._key(jti)))


# Module-level singleton -----------------------------------------------
token_store_service = TokenStoreService()


def get_token_store_service() -> TokenStoreService:
    """FastAPI dependency that returns the module-level TokenStoreService."""
    return token_store_service
