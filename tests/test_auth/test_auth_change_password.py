"""Integration tests for ``POST /api/v1/auth/change-password``."""

from collections.abc import Generator
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


def _login(client: TestClient) -> str:
    """Login the default user and return the access token."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "MyStr0ngP@ss!"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestChangePasswordSuccess:
    """``POST /auth/change-password`` — happy path (200)."""

    def test_successful_change(
        self,
        client: TestClient,
        db_session: Session,
        fake_redis: FakeRedis,
        email_producer_mock: AsyncMock,
    ) -> None:
        user = _seed_user(db_session)
        access_token = _login(client)

        # Ensure a refresh token exists
        fake_redis._store[f"refresh_token:{user.email}:some-jti"] = "1"

        response = client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "MyStr0ngP@ss!",
                "new_password": "NewStr0ng@Pass!",
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "message": "Password updated successfully.",
        }

        # Password should be updated
        db_session.refresh(user)
        svc = SecurityService()
        assert svc.verify_password("NewStr0ng@Pass!", user.hashed_password)
        assert not svc.verify_password("MyStr0ngP@ss!", user.hashed_password)

        # All refresh tokens should be revoked
        refresh_keys = [k for k in fake_redis._store if k.startswith("refresh_token:")]
        assert len(refresh_keys) == 0

        # Confirmation email should be sent
        email_producer_mock.send_email.assert_awaited()

    def test_access_token_still_works_after_change(
        self,
        client: TestClient,
        db_session: Session,
    ) -> None:
        """The current AT remains valid until natural expiry (not blacklisted)."""
        _seed_user(db_session)
        access_token = _login(client)

        # Change password
        client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "MyStr0ngP@ss!",
                "new_password": "NewStr0ng@Pass!",
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )

        # The same access token should still work for another change
        response = client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "NewStr0ng@Pass!",
                "new_password": "YetAnother@Pass1",
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 200


class TestChangePasswordIncorrect:
    """``POST /auth/change-password`` — wrong current password (400)."""

    def test_wrong_current_password_returns_400(
        self,
        client: TestClient,
        db_session: Session,
    ) -> None:
        _seed_user(db_session)
        access_token = _login(client)

        response = client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "WrongP@ssw0rd!",
                "new_password": "NewStr0ng@Pass!",
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert response.status_code == 400
        assert response.json() == {
            "status": "error",
            "code": "INCORRECT_PASSWORD",
            "message": "Current password is incorrect.",
            "details": [],
        }


class TestChangePasswordSame:
    """``POST /auth/change-password`` — same password (400)."""

    def test_same_password_returns_400(
        self,
        client: TestClient,
        db_session: Session,
    ) -> None:
        _seed_user(db_session)
        access_token = _login(client)

        response = client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "MyStr0ngP@ss!",
                "new_password": "MyStr0ngP@ss!",
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert response.status_code == 400
        assert response.json() == {
            "status": "error",
            "code": "SAME_PASSWORD",
            "message": "New password must be different from the current password.",
            "details": [],
        }


class TestChangePasswordUnauthenticated:
    """``POST /auth/change-password`` — no access token (401)."""

    def test_no_token_returns_401(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "Whatever!",
                "new_password": "NewP@ssw0rd!",
            },
        )
        assert response.status_code == 401


class TestChangePasswordValidation:
    """``POST /auth/change-password`` — input validation (422)."""

    def test_short_new_password_returns_422(
        self,
        client: TestClient,
        db_session: Session,
    ) -> None:
        _seed_user(db_session)
        access_token = _login(client)

        response = client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "MyStr0ngP@ss!",
                "new_password": "short",
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert response.status_code == 400
        assert response.json()["code"] == "VALIDATION_ERROR"


class TestChangePasswordRateLimit:
    """``POST /auth/change-password`` — rate-limit enforcement."""

    def test_rate_limit(
        self,
        client: TestClient,
        db_session: Session,
    ) -> None:
        _seed_user(db_session)
        access_token = _login(client)

        limiter.enabled = True
        try:
            for _ in range(10):
                response = client.post(
                    "/api/v1/auth/change-password",
                    json={
                        "current_password": "WrongP@ss!",
                        "new_password": "NewStr0ng@Pass!",
                    },
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "X-Forwarded-For": "127.0.0.99",
                    },
                )
                # Will be 400 (incorrect password) but not 429
                assert response.status_code == 400

            # 11th request should be rate limited
            response = client.post(
                "/api/v1/auth/change-password",
                json={
                    "current_password": "WrongP@ss!",
                    "new_password": "NewStr0ng@Pass!",
                },
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "X-Forwarded-For": "127.0.0.99",
                },
            )
            assert response.status_code == 429
        finally:
            limiter.enabled = False
