"""Integration tests for ``POST /api/v1/auth/refresh-token``."""

from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.rate_limiter import limiter
from app.core.security import SecurityService
from app.db.session import get_db
from app.main import app
from app.models.user import Base, User
from app.services.account_lockout import (
    AccountLockoutService,
    get_account_lockout_service,
)
from app.services.email_producer import get_email_producer_service
from app.services.token_store import TokenStoreService, get_token_store_service

# ---------------------------------------------------------------------------
# Fake Redis — supports SCAN for revoke_all_user_tokens
# ---------------------------------------------------------------------------


class FakeRedis:
    """In-memory stand-in for ``redis.asyncio.Redis`` with SCAN support."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,  # noqa: ARG002
    ) -> None:
        self._store[key] = value

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self._store.pop(key, None)

    async def exists(self, key: str) -> int:
        return 1 if key in self._store else 0

    async def incr(self, key: str) -> int:
        current = int(self._store.get(key, "0"))
        current += 1
        self._store[key] = str(current)
        return current

    async def scan(
        self,
        cursor: int,  # noqa: ARG002
        match: str | None = None,
        count: int | None = None,  # noqa: ARG002
    ) -> tuple[int, list[str]]:
        """Return all keys matching *match* pattern in one shot (cursor=0)."""
        import fnmatch

        if match:
            # Convert Redis glob to fnmatch (Redis uses * for wildcard)
            matched = [k for k in self._store if fnmatch.fnmatch(k, match)]
        else:
            matched = list(self._store.keys())
        # Return cursor=0 to signal iteration complete
        return 0, matched

    def pipeline(self) -> "FakePipeline":
        return FakePipeline(self)

    def reset(self) -> None:
        self._store.clear()


class FakePipeline:
    """Minimal pipeline stand-in that accumulates delete commands."""

    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis
        self._cmds: list[str] = []

    def delete(self, key: str) -> "FakePipeline":
        self._cmds.append(key)
        return self

    async def execute(self) -> None:
        for key in self._cmds:
            self._redis._store.pop(key, None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def email_producer_mock() -> AsyncMock:
    mock = AsyncMock()
    mock.send_email = AsyncMock()
    return mock


@pytest.fixture
def token_store(fake_redis: FakeRedis) -> TokenStoreService:
    return TokenStoreService(redis_client=fake_redis)  # type: ignore[arg-type]


@pytest.fixture
def lockout_svc(fake_redis: FakeRedis) -> AccountLockoutService:
    return AccountLockoutService(redis_client=fake_redis)  # type: ignore[arg-type]


@pytest.fixture
def client(
    db_session: Session,
    email_producer_mock: AsyncMock,
    token_store: TokenStoreService,
    lockout_svc: AccountLockoutService,
) -> Generator[TestClient, None, None]:
    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    def _override_email_producer() -> AsyncMock:
        return email_producer_mock

    def _override_token_store() -> TokenStoreService:
        return token_store

    def _override_lockout_svc() -> AccountLockoutService:
        return lockout_svc

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_email_producer_service] = _override_email_producer
    app.dependency_overrides[get_token_store_service] = _override_token_store
    app.dependency_overrides[get_account_lockout_service] = _override_lockout_svc

    limiter.enabled = False
    with TestClient(app) as test_client:
        yield test_client
    limiter.enabled = True
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_URL = "/api/v1/auth/refresh-token"
_SECURITY = SecurityService()


def _make_refresh_cookie(email: str) -> tuple[str, str, int]:
    """Return (raw_token, jti, ttl) for seeding a valid refresh cookie."""
    token, jti, ttl = _SECURITY.create_refresh_token(email=email)
    return token, jti, ttl


def _seed_user(
    db: Session,
    email: str = "refresh@example.com",
    is_active: bool = True,
    deleted_at: datetime | None = None,
) -> User:
    user = User(
        email=email.lower(),
        hashed_password=_SECURITY.hash_password("Passw0rd!"),
        full_name="Refresh User",
        is_active=is_active,
        is_verified=True,
        deleted_at=deleted_at,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestRefreshTokenSuccess:
    """Happy path: valid rotation returns new tokens and updates cookie."""

    def test_returns_200_with_new_access_token(
        self,
        client: TestClient,
        db_session: Session,
        token_store: TokenStoreService,
    ) -> None:
        email = "refresh@example.com"
        _seed_user(db_session, email=email)
        raw_token, jti, ttl = _make_refresh_cookie(email)

        # Manually seed the JTI into fake Redis (as the login endpoint would)
        import asyncio

        asyncio.get_event_loop().run_until_complete(
            token_store.save_refresh_token(email=email, jti=jti, ttl_seconds=ttl)
        )

        response = client.post(_URL, cookies={"refresh_token": raw_token})

        assert response.status_code == 200
        body = response.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert body["expires_in"] > 0

    def test_sets_new_httponly_refresh_cookie(
        self,
        client: TestClient,
        db_session: Session,
        token_store: TokenStoreService,
    ) -> None:
        email = "refresh@example.com"
        _seed_user(db_session, email=email)
        raw_token, jti, ttl = _make_refresh_cookie(email)

        import asyncio

        asyncio.get_event_loop().run_until_complete(
            token_store.save_refresh_token(email=email, jti=jti, ttl_seconds=ttl)
        )

        response = client.post(_URL, cookies={"refresh_token": raw_token})

        assert response.status_code == 200
        # TestClient exposes set-cookie as a header
        set_cookie = response.headers.get("set-cookie", "")
        assert "refresh_token=" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "SameSite=strict" in set_cookie

    def test_old_jti_revoked_after_rotation(
        self,
        client: TestClient,
        db_session: Session,
        token_store: TokenStoreService,
    ) -> None:
        email = "refresh@example.com"
        _seed_user(db_session, email=email)
        raw_token, jti, ttl = _make_refresh_cookie(email)

        import asyncio

        loop = asyncio.get_event_loop()
        loop.run_until_complete(
            token_store.save_refresh_token(email=email, jti=jti, ttl_seconds=ttl)
        )

        client.post(_URL, cookies={"refresh_token": raw_token})

        # Old JTI must no longer exist in Redis
        still_valid = loop.run_until_complete(
            token_store.is_refresh_token_valid(email=email, jti=jti)
        )
        assert not still_valid


class TestRefreshTokenMissingCookie:
    """No cookie provided."""

    def test_returns_401_missing_refresh_token(
        self, client: TestClient, db_session: Session
    ) -> None:
        _seed_user(db_session)
        response = client.post(_URL)  # no cookie

        assert response.status_code == 401
        assert response.json()["code"] == "MISSING_REFRESH_TOKEN"


class TestRefreshTokenInvalid:
    """Tampered or expired tokens."""

    def test_returns_401_for_garbage_token(
        self, client: TestClient, db_session: Session
    ) -> None:
        _seed_user(db_session)
        response = client.post(_URL, cookies={"refresh_token": "this.is.garbage"})

        assert response.status_code == 401
        assert response.json()["code"] == "INVALID_REFRESH_TOKEN"

    def test_returns_401_for_access_token_used_as_refresh(
        self, client: TestClient, db_session: Session
    ) -> None:
        """An access token must not be accepted as a refresh token."""
        _seed_user(db_session)
        access_token, _ = _SECURITY.create_access_token(email="refresh@example.com")

        response = client.post(_URL, cookies={"refresh_token": access_token})

        assert response.status_code == 401
        assert response.json()["code"] == "INVALID_REFRESH_TOKEN"


class TestRefreshTokenReuse:
    """Replay attack: using a JTI that was already revoked."""

    def test_returns_401_reuse_and_revokes_all_sessions(
        self,
        client: TestClient,
        db_session: Session,
        token_store: TokenStoreService,
    ) -> None:
        email = "refresh@example.com"
        _seed_user(db_session, email=email)
        raw_token, _jti, _ttl = _make_refresh_cookie(email)

        import asyncio

        loop = asyncio.get_event_loop()

        # Seed a second "live" token for the same user to confirm it also
        # gets wiped during the breach response.
        _, jti2, ttl2 = _make_refresh_cookie(email)
        loop.run_until_complete(
            token_store.save_refresh_token(email=email, jti=jti2, ttl_seconds=ttl2)
        )

        # Do NOT seed jti (simulate: old token already rotated/revoked)
        # Attempt to use it — this is a reuse attack
        response = client.post(_URL, cookies={"refresh_token": raw_token})

        assert response.status_code == 401
        assert response.json()["code"] == "REFRESH_TOKEN_REUSE"

        # The second live token should also be wiped
        still_valid = loop.run_until_complete(
            token_store.is_refresh_token_valid(email=email, jti=jti2)
        )
        assert not still_valid


class TestRefreshTokenDeactivatedAccount:
    """Account was deactivated after token was issued."""

    def test_returns_403_for_deleted_account(
        self,
        client: TestClient,
        db_session: Session,
        token_store: TokenStoreService,
    ) -> None:
        email = "gone@example.com"
        _seed_user(db_session, email=email, deleted_at=datetime.now(UTC))
        raw_token, jti, ttl = _make_refresh_cookie(email)

        import asyncio

        asyncio.get_event_loop().run_until_complete(
            token_store.save_refresh_token(email=email, jti=jti, ttl_seconds=ttl)
        )

        response = client.post(_URL, cookies={"refresh_token": raw_token})

        assert response.status_code == 403
        assert response.json()["code"] == "ACCOUNT_DEACTIVATED"

    def test_returns_403_for_inactive_account(
        self,
        client: TestClient,
        db_session: Session,
        token_store: TokenStoreService,
    ) -> None:
        email = "inactive@example.com"
        _seed_user(db_session, email=email, is_active=False)
        raw_token, jti, ttl = _make_refresh_cookie(email)

        import asyncio

        asyncio.get_event_loop().run_until_complete(
            token_store.save_refresh_token(email=email, jti=jti, ttl_seconds=ttl)
        )

        response = client.post(_URL, cookies={"refresh_token": raw_token})

        assert response.status_code == 403
        assert response.json()["code"] == "ACCOUNT_DEACTIVATED"
