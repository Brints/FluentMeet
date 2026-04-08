from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import get_db
from app.main import app
from app.models.base import Base
from app.modules.auth.models import User, VerificationToken
from app.services.email_producer import get_email_producer_service


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    db = testing_session_local()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def email_producer_mock() -> AsyncMock:
    mock = AsyncMock()
    mock.send_email = AsyncMock()
    return mock


@pytest.fixture
def client(
    db_session: Session, email_producer_mock: AsyncMock
) -> Generator[TestClient, None, None]:
    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    def _override_email_producer() -> AsyncMock:
        return email_producer_mock

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_email_producer_service] = _override_email_producer
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _create_unverified_user(client: TestClient, email: str) -> None:
    payload = {
        "email": email,
        "password": "MyStr0ngP@ss!",
        "full_name": "Email Verify",
    }
    response = client.post("/api/v1/auth/signup", json=payload)
    assert response.status_code == 201


def _get_verification_token(db_session: Session, email: str) -> VerificationToken:
    user = db_session.execute(select(User).where(User.email == email)).scalar_one()
    statement = select(VerificationToken).where(VerificationToken.user_id == user.id)
    return db_session.execute(statement).scalar_one()


def test_verify_email_success_marks_user_verified_and_deletes_token(
    client: TestClient,
    db_session: Session,
) -> None:
    email = "verify-success@example.com"
    _create_unverified_user(client, email)
    token = _get_verification_token(db_session, email)

    response = client.get(f"/api/v1/auth/verify-email?token={token.token}")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": "Email successfully verified. You can now log in.",
    }

    user = db_session.execute(select(User).where(User.email == email)).scalar_one()
    assert user.is_verified is True
    assert db_session.get(VerificationToken, token.id) is None


def test_verify_email_missing_token_returns_custom_error(client: TestClient) -> None:
    response = client.get("/api/v1/auth/verify-email")

    assert response.status_code == 400
    assert response.json() == {
        "status": "error",
        "code": "MISSING_TOKEN",
        "message": "Verification token is required.",
        "details": [],
    }


def test_verify_email_invalid_token_returns_custom_error(client: TestClient) -> None:
    response = client.get(
        "/api/v1/auth/verify-email?token=8f14e45f-ceea-4f6a-9fef-3d4d3e0d1be1"
    )

    assert response.status_code == 400
    assert response.json() == {
        "status": "error",
        "code": "INVALID_TOKEN",
        "message": "Verification token is invalid.",
        "details": [],
    }


def test_verify_email_expired_token_returns_token_expired(
    client: TestClient,
    db_session: Session,
) -> None:
    email = "verify-expired@example.com"
    _create_unverified_user(client, email)
    token = _get_verification_token(db_session, email)
    token.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()

    response = client.get(f"/api/v1/auth/verify-email?token={token.token}")

    assert response.status_code == 400
    assert response.json() == {
        "status": "error",
        "code": "TOKEN_EXPIRED",
        "message": "Verification token has expired. Please request a new one.",
        "details": [],
    }


def test_verify_email_already_verified_is_idempotent(
    client: TestClient,
    db_session: Session,
) -> None:
    email = "verify-idempotent@example.com"
    _create_unverified_user(client, email)
    token = _get_verification_token(db_session, email)

    user = db_session.execute(select(User).where(User.email == email)).scalar_one()
    user.is_verified = True
    db_session.commit()

    response = client.get(f"/api/v1/auth/verify-email?token={token.token}")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert db_session.get(VerificationToken, token.id) is None


def test_resend_verification_generates_new_token_and_enqueues_email(
    client: TestClient,
    db_session: Session,
    email_producer_mock: AsyncMock,
) -> None:
    email = "resend@example.com"
    _create_unverified_user(client, email)
    old_token = _get_verification_token(db_session, email)
    old_value = old_token.token
    email_producer_mock.send_email.reset_mock()

    response = client.post(
        "/api/v1/auth/resend-verification",
        json={"email": email},
    )

    assert response.status_code == 200
    assert response.json() == {
        "message": (
            "If an account with that email exists, we have sent a verification email."
        )
    }
    email_producer_mock.send_email.assert_awaited_once()

    new_token = _get_verification_token(db_session, email)
    assert new_token.token != old_value


def test_resend_verification_for_missing_user_is_enumeration_safe(
    client: TestClient,
    email_producer_mock: AsyncMock,
) -> None:
    response = client.post(
        "/api/v1/auth/resend-verification",
        json={"email": "not-found@example.com"},
    )

    assert response.status_code == 200
    assert response.json()["message"].startswith("If an account with that email exists")
    email_producer_mock.send_email.assert_not_awaited()
