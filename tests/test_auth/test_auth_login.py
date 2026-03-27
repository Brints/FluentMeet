"""Integration tests for ``POST /api/v1/auth/login``."""

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
from app.services.token_store import (
    TokenStoreService,
    get_token_store_service,
)

# ---------------------------------------------------------------------------
# Fake Redis for token-store and lockout without a real Redis instance
# ---------------------------------------------------------------------------


class FakeRedis:
    """In-memory stand-in for ``redis.asyncio.Redis``."""

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

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def exists(self, key: str) -> int:
        return 1 if key in self._store else 0

    async def incr(self, key: str) -> int:
        current = int(self._store.get(key, "0"))
        current += 1
        self._store[key] = str(current)
        return current

    def reset(self) -> None:
        self._store.clear()


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

    # Disable slowapi rate limiting so repeated test requests don't hit 429.
    limiter.enabled = False
    with TestClient(app) as test_client:
        yield test_client
    limiter.enabled = True
    app.dependency_overrides.clear()


def _seed_user(
    db: Session,
    *,
    email: str = "user@example.com",
    password: str = "MyStr0ngP@ss!",
    is_verified: bool = True,
    deleted_at: datetime | None = None,
) -> User:
    """Insert a user directly into the testing DB."""
    svc = SecurityService()
    user = User(
        email=email.lower(),
        hashed_password=svc.hash_password(password),
        full_name="Test User",
        is_active=True,
        is_verified=is_verified,
        deleted_at=deleted_at,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestLoginSuccess:
    """``POST /auth/login`` — happy path (200)."""

    def test_returns_access_token_and_user_id(
        self, client: TestClient, db_session: Session
    ) -> None:
        user = _seed_user(db_session)

        response = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "MyStr0ngP@ss!"},
        )

        assert response.status_code == 200
        body = response.json()
        assert "access_token" in body
        assert body["user_id"] == str(user.id)
        assert body["token_type"] == "bearer"
        assert body["expires_in"] > 0

    def test_sets_httponly_refresh_cookie(
        self, client: TestClient, db_session: Session
    ) -> None:
        _seed_user(db_session)

        response = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "MyStr0ngP@ss!"},
        )

        assert response.status_code == 200
        cookies = response.cookies
        assert "refresh_token" in cookies

    def test_refresh_token_not_in_body(
        self, client: TestClient, db_session: Session
    ) -> None:
        _seed_user(db_session)

        response = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "MyStr0ngP@ss!"},
        )

        assert response.status_code == 200
        body = response.json()
        assert "refresh_token" not in body

    def test_stores_refresh_jti_in_token_store(
        self,
        client: TestClient,
        db_session: Session,
        fake_redis: FakeRedis,
    ) -> None:
        _seed_user(db_session)

        response = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "MyStr0ngP@ss!"},
        )

        assert response.status_code == 200
        # At least one refresh_token:* key should exist
        refresh_keys = [k for k in fake_redis._store if k.startswith("refresh_token:")]
        assert len(refresh_keys) == 1


class TestLoginInvalidCredentials:
    """``POST /auth/login`` — wrong password / non-existent email (401)."""

    def test_wrong_password_returns_401(
        self, client: TestClient, db_session: Session
    ) -> None:
        _seed_user(db_session)

        response = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "WrongPassword!"},
        )

        assert response.status_code == 401
        assert response.json() == {
            "status": "error",
            "code": "INVALID_CREDENTIALS",
            "message": "Invalid email or password.",
            "details": [],
        }

    def test_nonexistent_email_returns_401(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "Whatever123!"},
        )

        assert response.status_code == 401
        assert response.json()["code"] == "INVALID_CREDENTIALS"

    def test_same_error_for_wrong_password_and_missing_email(
        self, client: TestClient, db_session: Session
    ) -> None:
        """No user-enumeration leakage."""
        _seed_user(db_session)

        wrong_pw = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "WrongPassword!"},
        )
        missing = client.post(
            "/api/v1/auth/login",
            json={"email": "ghost@example.com", "password": "Whatever123!"},
        )

        assert wrong_pw.json() == missing.json()


class TestLoginUnverifiedAccount:
    """``POST /auth/login`` — unverified email (403)."""

    def test_unverified_user_returns_403(
        self, client: TestClient, db_session: Session
    ) -> None:
        _seed_user(db_session, is_verified=False)

        response = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "MyStr0ngP@ss!"},
        )

        assert response.status_code == 403
        assert response.json() == {
            "status": "error",
            "code": "EMAIL_NOT_VERIFIED",
            "message": "Please verify your email before logging in.",
            "details": [],
        }


class TestLoginDeletedAccount:
    """``POST /auth/login`` — soft-deleted user (403)."""

    def test_deleted_user_returns_403(
        self, client: TestClient, db_session: Session
    ) -> None:
        _seed_user(db_session, deleted_at=datetime.now(UTC))

        response = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "MyStr0ngP@ss!"},
        )

        assert response.status_code == 403
        assert response.json() == {
            "status": "error",
            "code": "ACCOUNT_DELETED",
            "message": "This account has been deleted.",
            "details": [],
        }


class TestLoginAccountLockout:
    """``POST /auth/login`` — lockout after 5 failures (403)."""

    def test_locked_account_returns_403(
        self,
        client: TestClient,
        db_session: Session,
        fake_redis: FakeRedis,
    ) -> None:
        _seed_user(db_session)

        # Simulate 5 failed attempts by writing the lock key directly
        fake_redis._store["account_locked:user@example.com"] = "1"

        response = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "MyStr0ngP@ss!"},
        )

        assert response.status_code == 403
        assert response.json()["code"] == "ACCOUNT_LOCKED"

    def test_five_failures_triggers_lockout(
        self,
        client: TestClient,
        db_session: Session,
    ) -> None:
        _seed_user(db_session)

        for _ in range(5):
            client.post(
                "/api/v1/auth/login",
                json={"email": "user@example.com", "password": "WrongPassword!"},
            )

        # The next attempt (even with the correct password) should be locked
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "MyStr0ngP@ss!"},
        )

        assert response.status_code == 403
        assert response.json()["code"] == "ACCOUNT_LOCKED"

    def test_successful_login_resets_counter(
        self,
        client: TestClient,
        db_session: Session,
        fake_redis: FakeRedis,
    ) -> None:
        _seed_user(db_session)

        # 4 failures (just under threshold)
        for _ in range(4):
            client.post(
                "/api/v1/auth/login",
                json={"email": "user@example.com", "password": "WrongPassword!"},
            )

        # Successful login resets the counter
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "MyStr0ngP@ss!"},
        )
        assert response.status_code == 200

        # Counter should be cleared
        assert "login_attempts:user@example.com" not in fake_redis._store
