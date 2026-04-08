"""Integration tests for ``POST /routers/v1/auth/forgot-password``."""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
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


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestForgotPassword:
    def test_registered_email_creates_token_and_sends_email(
        self, client: TestClient, db_session: Session, email_producer_mock: AsyncMock
    ) -> None:
        user = _seed_user(db_session, is_verified=True)

        response = client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "user@example.com"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "message": "If an account with this email exists, a password reset link has been sent.",  # noqa: E501
        }

        # Token created
        token = db_session.scalars(
            select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
        ).first()
        assert token is not None

        # Email sent
        email_producer_mock.send_email.assert_awaited_once()
        _, kwargs = email_producer_mock.send_email.call_args
        assert kwargs["to"] == "user@example.com"
        assert kwargs["template"] == "password_reset"
        assert "reset_link" in kwargs["template_data"]

    def test_unknown_email_returns_success_but_no_side_effects(
        self, client: TestClient, db_session: Session, email_producer_mock: AsyncMock
    ) -> None:
        response = client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "unknown@example.com"},
        )

        assert response.status_code == 200

        # No tokens created
        tokens = db_session.scalars(select(PasswordResetToken)).all()
        assert len(tokens) == 0

        # No email sent
        email_producer_mock.send_email.assert_not_called()

    def test_existing_token_is_replaced(
        self, client: TestClient, db_session: Session
    ) -> None:
        user = _seed_user(db_session, is_verified=True)

        # Create old token
        old_token = PasswordResetToken(
            user_id=user.id, expires_at=datetime.now(UTC) + timedelta(minutes=60)
        )
        db_session.add(old_token)
        db_session.commit()
        db_session.refresh(old_token)

        old_token_id = old_token.id

        response = client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "user@example.com"},
        )
        assert response.status_code == 200

        tokens = db_session.scalars(
            select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
        ).all()
        assert len(tokens) == 1
        assert tokens[0].id != old_token_id

    def test_rate_limit(self, client: TestClient, db_session: Session) -> None:
        _seed_user(db_session, email="rate@example.com", is_verified=True)
        # Re-enable rate limiter carefully using
        # the underlying request mock so 429 is propagated
        limiter.enabled = True
        try:
            for _ in range(5):
                response = client.post(
                    "/api/v1/auth/forgot-password",
                    json={"email": "rate@example.com"},
                    headers={"X-Forwarded-For": "127.0.0.99"},
                )
                assert response.status_code == 200

            # 6th request should fail with 429 Too Many Requests
            response = client.post(
                "/api/v1/auth/forgot-password",
                json={"email": "rate@example.com"},
                headers={"X-Forwarded-For": "127.0.0.99"},
            )
            assert response.status_code == 429
        finally:
            limiter.enabled = False
