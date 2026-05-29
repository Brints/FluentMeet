from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from app.core.security import SecurityService
from app.models.base import Base
from app.modules.auth.models import User
from app.modules.auth.service import AuthService


@pytest.fixture
def db_session():
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
def auth_service(db_session):
    sec_mock = MagicMock(spec=SecurityService)
    sec_mock.hash_password.return_value = "hashed_pass"
    sec_mock.create_access_token.return_value = ("access_tok", 3600)
    sec_mock.create_refresh_token.return_value = ("refresh_tok", "jti_123", 86400)

    email_mock = MagicMock()
    ver_mock = MagicMock()
    lock_mock = AsyncMock()
    lock_mock.is_locked.return_value = False
    store_mock = AsyncMock()

    return AuthService(
        db=db_session,
        security_service=sec_mock,
        email_producer=email_mock,
        auth_verification_service=ver_mock,
        lockout_svc=lock_mock,
        token_store=store_mock,
    )


@pytest.mark.asyncio
async def test_resolve_oauth_user_signup_new_user(auth_service, db_session):
    login_response, _rt, _rt_ttl, is_new = await auth_service.resolve_oauth_user(
        email="newuser@example.com",
        google_id="google_new",
        name="New User",
        avatar_url="http://avatar.png",
        flow="signup",
    )
    assert is_new is True
    assert login_response.access_token == "access_tok"

    # Verify user exists in DB
    user = db_session.query(User).filter_by(email="newuser@example.com").first()
    assert user is not None
    assert user.google_id == "google_new"
    assert user.is_verified is True


@pytest.mark.asyncio
async def test_resolve_oauth_user_signup_existing_conflict(auth_service, db_session):
    # Create existing user
    user = User(
        email="existing@example.com",
        hashed_password="some_password",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    db_session.commit()

    with pytest.raises(ConflictException) as excinfo:
        await auth_service.resolve_oauth_user(
            email="existing@example.com",
            google_id="google_id",
            name="Existing",
            avatar_url=None,
            flow="signup",
        )
    assert excinfo.value.code == "EMAIL_ALREADY_REGISTERED"


@pytest.mark.asyncio
async def test_resolve_oauth_user_login_success(auth_service, db_session):
    # Create existing user with google_id
    user = User(
        email="googleuser@example.com",
        hashed_password="some_password",
        google_id="google_123",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    db_session.commit()

    login_response, _rt, _rt_ttl, is_new = await auth_service.resolve_oauth_user(
        email="googleuser@example.com",
        google_id="google_123",
        name="Google User",
        avatar_url="http://avatar.png",
        flow="login",
    )
    assert is_new is False
    assert login_response.access_token == "access_tok"


@pytest.mark.asyncio
async def test_resolve_oauth_user_login_nonexistent(auth_service):
    with pytest.raises(NotFoundException) as excinfo:
        await auth_service.resolve_oauth_user(
            email="nonexistent@example.com",
            google_id="google_123",
            name="Nonexistent",
            avatar_url=None,
            flow="login",
        )
    assert excinfo.value.code == "ACCOUNT_NOT_FOUND"


@pytest.mark.asyncio
async def test_resolve_oauth_user_login_method_mismatch(auth_service, db_session):
    # User exists but google_id is NOT set (email/password user)
    user = User(
        email="emailpwd@example.com",
        hashed_password="some_password",
        google_id=None,
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    db_session.commit()

    with pytest.raises(BadRequestException) as excinfo:
        await auth_service.resolve_oauth_user(
            email="emailpwd@example.com",
            google_id="google_123",
            name="Email Password User",
            avatar_url=None,
            flow="login",
        )
    assert excinfo.value.code == "AUTH_METHOD_MISMATCH"
