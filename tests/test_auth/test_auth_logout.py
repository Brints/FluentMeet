"""Integration tests for ``POST /api/v1/auth/logout``."""

from collections.abc import Generator
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.rate_limiter import limiter
from app.db.session import get_db
from app.main import app
from app.models.base import Base
from app.modules.auth.account_lockout import (
    AccountLockoutService,
    get_account_lockout_service,
)
from app.modules.auth.token_store import (
    TokenStoreService,
    get_token_store_service,
)
from app.services.email_producer import get_email_producer_service
from tests.test_auth.test_auth_login import FakeRedis, _seed_user

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


def _login_and_get_tokens(
    client: TestClient,
) -> tuple[str, str | None]:
    """Login the default user and return (access_token, refresh_token_cookie)."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "MyStr0ngP@ss!"},
    )
    assert response.status_code == 200
    access_token = response.json()["access_token"]
    refresh_token = response.cookies.get("refresh_token")
    return access_token, refresh_token


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestLogoutSuccess:
    """``POST /auth/logout`` — happy path (200)."""

    def test_successful_logout(
        self,
        client: TestClient,
        db_session: Session,
        fake_redis: FakeRedis,
    ) -> None:
        _seed_user(db_session)
        access_token, _refresh_token = _login_and_get_tokens(client)

        response = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body == {"status": "ok", "message": "Successfully logged out."}

        # AT should be blacklisted
        blacklist_keys = [
            k for k in fake_redis._store if k.startswith("blacklisted_access_token:")
        ]
        assert len(blacklist_keys) == 1

    def test_logout_blacklists_access_token(
        self,
        client: TestClient,
        db_session: Session,
    ) -> None:
        _seed_user(db_session)
        access_token, _refresh_token = _login_and_get_tokens(client)

        # Logout
        response = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 200

        # Subsequent request with the same AT should be rejected
        response = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 401
        assert response.json()["code"] == "TOKEN_REVOKED"

    def test_logout_without_refresh_cookie_still_succeeds(
        self,
        client: TestClient,
        db_session: Session,
        fake_redis: FakeRedis,
    ) -> None:
        _seed_user(db_session)
        access_token, _ = _login_and_get_tokens(client)

        # Clear cookies to simulate a missing RT cookie
        client.cookies.clear()

        response = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert response.status_code == 200

        # AT should still be blacklisted
        blacklist_keys = [
            k for k in fake_redis._store if k.startswith("blacklisted_access_token:")
        ]
        assert len(blacklist_keys) == 1


class TestLogoutUnauthenticated:
    """``POST /auth/logout`` — no access token (401)."""

    def test_no_token_returns_401(self, client: TestClient) -> None:
        response = client.post("/api/v1/auth/logout")
        assert response.status_code == 401


class TestLogoutRateLimit:
    """``POST /auth/logout`` — rate-limit enforcement."""

    def test_rate_limit(
        self,
        client: TestClient,
        db_session: Session,
    ) -> None:
        user = _seed_user(db_session)
        from app.core.security import SecurityService

        svc = SecurityService()

        limiter.enabled = True
        try:
            for i in range(20):
                # Use directly generated tokens to avoid hitting the /login rate limit
                access_token, _ = svc.create_access_token(user.email)
                response = client.post(
                    "/api/v1/auth/logout",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "X-Forwarded-For": "127.0.0.99",
                    },
                )
                assert response.status_code == 200, f"Request {i + 1} failed"

            # 21st should be rate limited
            access_token, _ = svc.create_access_token(user.email)
            response = client.post(
                "/api/v1/auth/logout",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "X-Forwarded-For": "127.0.0.99",
                },
            )
            assert response.status_code == 429
        finally:
            limiter.enabled = False
