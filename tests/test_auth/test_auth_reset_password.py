"""Integration tests for ``POST /api/v1/auth/reset-password``."""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
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
from app.modules.auth.models import PasswordResetToken
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


def _create_reset_token(
    db: Session,
    user_id: "object",
    *,
    expired: bool = False,
) -> PasswordResetToken:
    """Create a password-reset token for a user."""
    if expired:
        expires_at = datetime.now(UTC) - timedelta(hours=1)
    else:
        expires_at = datetime.now(UTC) + timedelta(hours=1)

    token = PasswordResetToken(user_id=user_id, expires_at=expires_at)
    db.add(token)
    db.commit()
    db.refresh(token)
    return token


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestResetPasswordSuccess:
    """``POST /auth/reset-password`` — happy path (200)."""

    def test_valid_reset(
        self,
        client: TestClient,
        db_session: Session,
        fake_redis: FakeRedis,
        email_producer_mock: AsyncMock,
    ) -> None:
        user = _seed_user(db_session, is_verified=True)
        reset_token = _create_reset_token(db_session, user.id)

        # Simulate an active refresh token in Redis
        fake_redis._store[f"refresh_token:{user.email}:some-jti"] = "1"

        response = client.post(
            "/api/v1/auth/reset-password",
            json={
                "token": reset_token.token,
                "new_password": "NewStr0ng@Pass!",
            },
        )

        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "message": (
                "Password has been reset successfully. Please log in with your new password."  # noqa: E501
            ),
        }

        # Token should be deleted
        remaining = db_session.scalars(
            select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
        ).all()
        assert len(remaining) == 0

        # Password should be updated
        db_session.refresh(user)
        svc = SecurityService()
        assert svc.verify_password("NewStr0ng@Pass!", user.hashed_password)

        # All refresh tokens should be revoked
        refresh_keys = [k for k in fake_redis._store if k.startswith("refresh_token:")]
        assert len(refresh_keys) == 0

        # Confirmation email should be sent
        email_producer_mock.send_email.assert_awaited()

    def test_can_login_with_new_password_after_reset(
        self,
        client: TestClient,
        db_session: Session,
    ) -> None:
        user = _seed_user(db_session, is_verified=True)
        reset_token = _create_reset_token(db_session, user.id)

        client.post(
            "/api/v1/auth/reset-password",
            json={
                "token": reset_token.token,
                "new_password": "BrandNewP@ss!",
            },
        )

        # Login with old password should fail
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "MyStr0ngP@ss!"},
        )
        assert response.status_code == 401

        # Login with new password should succeed
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "BrandNewP@ss!"},
        )
        assert response.status_code == 200


class TestResetPasswordInvalidToken:
    """``POST /auth/reset-password`` — invalid token (400)."""

    def test_invalid_token_returns_400(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/reset-password",
            json={
                "token": "non-existent-token",
                "new_password": "SomeP@ssw0rd!",
            },
        )

        assert response.status_code == 400
        assert response.json() == {
            "status": "error",
            "code": "INVALID_RESET_TOKEN",
            "message": "Password reset token is invalid.",
            "details": [],
        }


class TestResetPasswordExpiredToken:
    """``POST /auth/reset-password`` — expired token (400)."""

    def test_expired_token_returns_400(
        self,
        client: TestClient,
        db_session: Session,
    ) -> None:
        user = _seed_user(db_session, is_verified=True)
        reset_token = _create_reset_token(db_session, user.id, expired=True)

        response = client.post(
            "/api/v1/auth/reset-password",
            json={
                "token": reset_token.token,
                "new_password": "SomeP@ssw0rd!",
            },
        )

        assert response.status_code == 400
        assert response.json() == {
            "status": "error",
            "code": "RESET_TOKEN_EXPIRED",
            "message": "Password reset token has expired. Please request a new one.",
            "details": [],
        }


class TestResetPasswordSamePassword:
    """``POST /auth/reset-password`` — same password as current (400)."""

    def test_same_password_returns_400(
        self,
        client: TestClient,
        db_session: Session,
    ) -> None:
        user = _seed_user(db_session, is_verified=True, password="MyStr0ngP@ss!")
        reset_token = _create_reset_token(db_session, user.id)

        response = client.post(
            "/api/v1/auth/reset-password",
            json={
                "token": reset_token.token,
                "new_password": "MyStr0ngP@ss!",
            },
        )

        assert response.status_code == 400
        assert response.json()["code"] == "SAME_PASSWORD"


class TestResetPasswordRateLimit:
    """``POST /auth/reset-password`` — rate-limit enforcement."""

    def test_rate_limit(
        self,
        client: TestClient,
    ) -> None:
        limiter.enabled = True
        try:
            for _ in range(5):
                response = client.post(
                    "/api/v1/auth/reset-password",
                    json={
                        "token": "dummy-token",
                        "new_password": "SomeP@ssw0rd!",
                    },
                    headers={"X-Forwarded-For": "127.0.0.99"},
                )
                # Will be 400 (invalid token) but not 429
                assert response.status_code == 400

            # 6th request should be rate limited
            response = client.post(
                "/api/v1/auth/reset-password",
                json={
                    "token": "dummy-token",
                    "new_password": "SomeP@ssw0rd!",
                },
                headers={"X-Forwarded-For": "127.0.0.99"},
            )
            assert response.status_code == 429
        finally:
            limiter.enabled = False
