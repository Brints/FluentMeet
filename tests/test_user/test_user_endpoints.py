"""Integration tests for user profile endpoints.

Tests ``GET /me``, ``PATCH /me``, ``POST /me/avatar``, and
``DELETE /me`` via :class:`~fastapi.testclient.TestClient` backed
by an in-memory SQLite database.
"""

import uuid
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.models import User
from app.auth.token_store import TokenStoreService, get_token_store_service
from app.core.config import settings
from app.core.dependencies import get_current_user
from app.core.security import SecurityService
from app.db.session import get_db
from app.external_services.cloudinary.service import (
    StorageService,
    get_storage_service,
)
from app.main import app
from app.models.base import Base
from app.services.email_producer import get_email_producer_service


# ── Fixtures ──────────────────────────────────────────────────────────

TEST_USER_ID = uuid.uuid4()
TEST_EMAIL = "testuser@example.com"


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
def sample_user(db_session: Session) -> User:
    """Insert a verified, active user into the test database."""
    user = User(
        id=TEST_USER_ID,
        email=TEST_EMAIL,
        hashed_password="$2b$12$fakehash",
        full_name="Ada Lovelace",
        is_active=True,
        is_verified=True,
        speaking_language="en",
        listening_language="fr",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def email_producer_mock() -> AsyncMock:
    mock = AsyncMock()
    mock.send_email = AsyncMock()
    return mock


@pytest.fixture
def token_store_mock() -> AsyncMock:
    mock = AsyncMock(spec=TokenStoreService)
    mock.is_access_token_blacklisted = AsyncMock(return_value=False)
    mock.revoke_all_user_tokens = AsyncMock()
    mock.blacklist_access_token = AsyncMock()
    return mock


@pytest.fixture
def storage_service_mock() -> AsyncMock:
    mock = AsyncMock(spec=StorageService)
    return mock


@pytest.fixture
def client(
    db_session: Session,
    sample_user: User,
    email_producer_mock: AsyncMock,
    token_store_mock: AsyncMock,
    storage_service_mock: AsyncMock,
) -> Generator[TestClient, None, None]:
    """TestClient with all external deps mocked and auth bypassed."""

    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    def _override_email_producer() -> AsyncMock:
        return email_producer_mock

    def _override_get_current_user() -> User:
        return sample_user

    def _override_get_token_store() -> AsyncMock:
        return token_store_mock

    def _override_get_storage() -> AsyncMock:
        return storage_service_mock

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_email_producer_service] = _override_email_producer
    app.dependency_overrides[get_current_user] = _override_get_current_user
    app.dependency_overrides[get_token_store_service] = _override_get_token_store
    app.dependency_overrides[get_storage_service] = _override_get_storage

    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def unauthenticated_client(
    db_session: Session,
    email_producer_mock: AsyncMock,
) -> Generator[TestClient, None, None]:
    """TestClient *without* auth override — endpoints should reject."""

    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    def _override_email_producer() -> AsyncMock:
        return email_producer_mock

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_email_producer_service] = _override_email_producer

    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ======================================================================
# GET /api/v1/users/me
# ======================================================================


class TestGetProfile:
    def test_returns_user_profile(self, client: TestClient) -> None:
        response = client.get("/api/v1/users/me")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["message"] == "User profile retrieved successfully."
        data = body["data"]
        assert data["email"] == TEST_EMAIL
        assert data["full_name"] == "Ada Lovelace"
        assert data["speaking_language"] == "en"
        assert data["listening_language"] == "fr"
        assert data["is_active"] is True
        assert data["is_verified"] is True

    def test_excludes_internal_fields(self, client: TestClient) -> None:
        response = client.get("/api/v1/users/me")
        data = response.json()["data"]
        assert "hashed_password" not in data
        assert "deleted_at" not in data
        assert "updated_at" not in data

    def test_unauthorized_without_token(
        self, unauthenticated_client: TestClient
    ) -> None:
        response = unauthenticated_client.get("/api/v1/users/me")
        assert response.status_code == 401


# ======================================================================
# PATCH /api/v1/users/me
# ======================================================================


class TestUpdateProfile:
    def test_update_full_name(self, client: TestClient) -> None:
        response = client.patch(
            "/api/v1/users/me",
            json={"full_name": "Ada K. Lovelace"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["full_name"] == "Ada K. Lovelace"

    def test_update_languages(self, client: TestClient) -> None:
        response = client.patch(
            "/api/v1/users/me",
            json={"speaking_language": "de", "listening_language": "es"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["speaking_language"] == "de"
        assert data["listening_language"] == "es"

    def test_empty_body_no_change(self, client: TestClient) -> None:
        response = client.patch("/api/v1/users/me", json={})
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["full_name"] == "Ada Lovelace"  # unchanged

    def test_invalid_language_returns_400(self, client: TestClient) -> None:
        response = client.patch(
            "/api/v1/users/me",
            json={"speaking_language": "zz"},
        )
        assert response.status_code == 400
        body = response.json()
        assert body["code"] == "VALIDATION_ERROR"

    def test_unauthorized(self, unauthenticated_client: TestClient) -> None:
        response = unauthenticated_client.patch(
            "/api/v1/users/me", json={"full_name": "X"}
        )
        assert response.status_code == 401


# ======================================================================
# POST /api/v1/users/me/avatar
# ======================================================================


class TestUploadAvatar:
    def test_upload_avatar_success(
        self,
        client: TestClient,
        storage_service_mock: AsyncMock,
    ) -> None:
        # Configure the mock to return a fake upload result.
        from app.external_services.cloudinary.schemas import UploadResult

        storage_service_mock.upload_image = AsyncMock(
            return_value=UploadResult(
                public_id=f"fluentmeet/avatars/{TEST_USER_ID}",
                secure_url="https://res.cloudinary.com/demo/image/upload/v1/fluentmeet/avatars/test.jpg",
                resource_type="image",
                format="jpg",
                bytes=12345,
                width=400,
                height=400,
            )
        )

        # Fake JPEG file content.
        file_content = b"\xff\xd8\xff\xe0" + b"\x00" * 100

        response = client.post(
            "/api/v1/users/me/avatar",
            files={"avatar": ("avatar.jpg", file_content, "image/jpeg")},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["message"] == "Avatar uploaded successfully."
        assert "avatar_url" in body["data"]
        storage_service_mock.upload_image.assert_awaited_once()

    def test_unauthorized(self, unauthenticated_client: TestClient) -> None:
        response = unauthenticated_client.post(
            "/api/v1/users/me/avatar",
            files={"avatar": ("a.jpg", b"\xff\xd8", "image/jpeg")},
        )
        assert response.status_code == 401


# ======================================================================
# DELETE /api/v1/users/me
# ======================================================================


class TestDeleteAccount:
    def test_soft_delete_default(
        self,
        client: TestClient,
        db_session: Session,
        sample_user: User,
        token_store_mock: AsyncMock,
    ) -> None:
        response = client.delete("/api/v1/users/me")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert "deactivated" in body["message"].lower() or "deleted" in body["message"].lower()

        # Verify DB state — user is soft-deleted.
        refreshed = db_session.execute(
            select(User).where(User.id == sample_user.id)
        ).scalar_one()
        assert refreshed.deleted_at is not None
        assert refreshed.is_active is False

        # Session teardown was called.
        token_store_mock.revoke_all_user_tokens.assert_awaited_once_with(TEST_EMAIL)

    def test_hard_delete(
        self,
        client: TestClient,
        db_session: Session,
        sample_user: User,
        token_store_mock: AsyncMock,
    ) -> None:
        response = client.delete("/api/v1/users/me?hard=true")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"

        # User should be physically gone from DB.
        result = db_session.execute(
            select(User).where(User.id == sample_user.id)
        ).scalar_one_or_none()
        assert result is None

        token_store_mock.revoke_all_user_tokens.assert_awaited_once_with(TEST_EMAIL)

    def test_delete_clears_refresh_cookie(
        self, client: TestClient
    ) -> None:
        response = client.delete("/api/v1/users/me")
        cookie_header = response.headers.get("set-cookie", "")
        # The response should clear the refresh_token cookie.
        assert "refresh_token" in cookie_header
        # Max-Age=0 or expires in the past signals deletion.
        assert 'Max-Age=0' in cookie_header or "max-age=0" in cookie_header

    def test_unauthorized(self, unauthenticated_client: TestClient) -> None:
        response = unauthenticated_client.delete("/api/v1/users/me")
        assert response.status_code == 401
