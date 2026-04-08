from collections.abc import Generator
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import get_db
from app.main import app
from app.models.base import Base
from app.modules.auth.models import User
from app.services.email_producer import get_email_producer_service


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


def test_signup_success_creates_user_and_returns_public_profile(
    client: TestClient,
    db_session: Session,
    email_producer_mock: AsyncMock,
) -> None:
    payload = {
        "email": "  USER@example.com  ",
        "password": "MyStr0ngP@ss!",
        "full_name": "  Ada Lovelace  ",
        "speaking_language": "en",
        "listening_language": "fr",
    }

    response = client.post("/api/v1/auth/signup", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "user@example.com"
    assert body["full_name"] == "Ada Lovelace"
    assert body["speaking_language"] == "en"
    assert body["listening_language"] == "fr"
    assert body["is_active"] is True
    assert body["is_verified"] is False
    assert "password" not in body
    assert "hashed_password" not in body

    created_user = db_session.execute(
        select(User).where(User.email == "user@example.com")
    ).scalar_one()
    assert created_user.hashed_password != payload["password"]
    assert created_user.hashed_password.startswith("$2")
    assert created_user.is_active is True
    assert created_user.is_verified is False
    email_producer_mock.send_email.assert_awaited_once()


def test_signup_duplicate_email_returns_conflict(client: TestClient) -> None:
    payload = {
        "email": "duplicate@example.com",
        "password": "MyStr0ngP@ss!",
        "full_name": "Duplicate User",
    }

    first = client.post("/api/v1/auth/signup", json=payload)
    second = client.post("/api/v1/auth/signup", json=payload)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json() == {
        "status": "error",
        "code": "EMAIL_ALREADY_REGISTERED",
        "message": "An account with this email already exists.",
        "details": [],
    }


def test_signup_invalid_language_uses_standard_validation_shape(
    client: TestClient,
) -> None:
    payload = {
        "email": "user2@example.com",
        "password": "MyStr0ngP@ss!",
        "speaking_language": "zz",
    }

    response = client.post("/api/v1/auth/signup", json=payload)

    assert response.status_code == 400
    body = response.json()
    assert body["status"] == "error"
    assert body["code"] == "VALIDATION_ERROR"
    fields = [detail["field"] for detail in body["details"]]
    assert "body.speaking_language" in fields


def test_forgot_password_returns_generic_accepted_response(
    client: TestClient, email_producer_mock: AsyncMock
) -> None:
    payload = {
        "email": "missing-user@example.com",
    }

    response = client.post("/api/v1/auth/forgot-password", json=payload)

    assert response.status_code == 202
    assert response.json() == {
        "message": (
            "If an account with that email exists,"
            " we have sent password reset instructions."
        )
    }
    email_producer_mock.send_email.assert_not_awaited()


def test_forgot_password_enqueues_reset_email_for_existing_user(
    client: TestClient,
    email_producer_mock: AsyncMock,
) -> None:
    signup_payload = {
        "email": "pwreset@example.com",
        "password": "MyStr0ngP@ss!",
        "full_name": "Reset User",
    }
    assert client.post("/api/v1/auth/signup", json=signup_payload).status_code == 201
    email_producer_mock.send_email.reset_mock()

    response = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "pwreset@example.com"},
    )

    assert response.status_code == 202
    email_producer_mock.send_email.assert_awaited_once()
