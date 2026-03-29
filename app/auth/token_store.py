"""Redis-backed refresh-token persistence.

Stores refresh-token JTIs in Redis so they can be validated during
token rotation and revoked on logout or on reuse-attack detection.

Key schema: ``refresh_token:{email}:{jti}``

Using the email as part of the key allows ``revoke_all_user_tokens``
to efficiently scan and delete every active session for a given user
without maintaining a secondary index.
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


class TokenStoreService:
    """Manages refresh-token JTIs in Redis.

    Each stored key has the shape ``refresh_token:{email}:{jti}`` with
    a TTL that mirrors the token's own expiry, so stale entries are
    cleaned up automatically.

    The email prefix makes per-user revocation (reuse-attack response)
    efficient: ``SCAN MATCH refresh_token:{email}:*`` instead of a
    full-keyspace scan.
    """

    PREFIX = "refresh_token"

    def __init__(self, redis_client: aioredis.Redis | None = None) -> None:
        self._redis = redis_client or _get_redis_client()

    def _key(self, email: str, jti: str) -> str:
        return f"{self.PREFIX}:{email}:{jti}"

    def _pattern(self, email: str) -> str:
        return f"{self.PREFIX}:{email}:*"

    async def save_refresh_token(self, email: str, jti: str, ttl_seconds: int) -> None:
        """Persist *jti* for *email* with an automatic expiry of *ttl_seconds*."""
        await self._redis.set(self._key(email, jti), "1", ex=ttl_seconds)

    async def revoke_refresh_token(self, email: str, jti: str) -> None:
        """Remove *jti* for *email*, effectively revoking the refresh token."""
        await self._redis.delete(self._key(email, jti))

    async def is_refresh_token_valid(self, email: str, jti: str) -> bool:
        """Return ``True`` if *jti* exists for *email* (not revoked/expired)."""
        return bool(await self._redis.exists(self._key(email, jti)))

    async def revoke_all_user_tokens(self, email: str) -> None:
        """Revoke every active refresh token for *email*.

        Called when reuse of a revoked token is detected, indicating a
        potential session-theft replay attack. Scans Redis for all keys
        matching ``refresh_token:{email}:*`` and deletes them in a single
        pipeline call.
        """
        pattern = self._pattern(email)
        keys_to_delete: list[str] = []

        # SCAN is non-blocking and cursor-safe for large keyspaces.
        cursor: int = 0
        while True:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
            keys_to_delete.extend(keys)
            if cursor == 0:
                break

        if keys_to_delete:
            pipe = self._redis.pipeline()
            for key in keys_to_delete:
                pipe.delete(key)
            await pipe.execute()
            logger.warning(
                "Revoked %d token(s) for %s due to refresh-token reuse.",
                len(keys_to_delete),
                sanitize_for_log(email),
            )


# Module-level singleton -----------------------------------------------
token_store_service = TokenStoreService()


def get_token_store_service() -> TokenStoreService:
    """FastAPI dependency that returns the module-level TokenStoreService."""
    return token_store_service
