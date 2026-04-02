"""Unit tests for ``app.user.service.UserService``."""

import uuid
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.models import User, VerificationToken
from app.models.base import Base
from app.user.service import UserService


# ── Fixtures ──────────────────────────────────────────────────────────


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
def user_service(db_session: Session) -> UserService:
    return UserService(db=db_session)


@pytest.fixture
def sample_user(db_session: Session) -> User:
    user = User(
        id=uuid.uuid4(),
        email="test@example.com",
        hashed_password="$2b$12$fakehash",
        full_name="Test User",
        is_active=True,
        is_verified=True,
        speaking_language="en",
        listening_language="en",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


# ── get_user_by_id ────────────────────────────────────────────────────


def test_get_user_by_id_returns_existing_user(
    user_service: UserService,
    sample_user: User,
) -> None:
    found = user_service.get_user_by_id(sample_user.id)
    assert found is not None
    assert found.id == sample_user.id
    assert found.email == "test@example.com"


def test_get_user_by_id_returns_none_for_unknown(
    user_service: UserService,
) -> None:
    assert user_service.get_user_by_id(uuid.uuid4()) is None


# ── update_user ───────────────────────────────────────────────────────


def test_update_user_partial_name(
    user_service: UserService,
    sample_user: User,
) -> None:
    updated = user_service.update_user(sample_user, {"full_name": "New Name"})
    assert updated.full_name == "New Name"
    assert updated.speaking_language == "en"  # unchanged


def test_update_user_language(
    user_service: UserService,
    sample_user: User,
) -> None:
    updated = user_service.update_user(
        sample_user, {"speaking_language": "fr", "listening_language": "de"}
    )
    assert updated.speaking_language == "fr"
    assert updated.listening_language == "de"


def test_update_user_skips_none_values(
    user_service: UserService,
    sample_user: User,
) -> None:
    updated = user_service.update_user(
        sample_user, {"full_name": None, "speaking_language": "es"}
    )
    assert updated.full_name == "Test User"  # unchanged (None skipped)
    assert updated.speaking_language == "es"


# ── update_avatar_url ────────────────────────────────────────────────


def test_update_avatar_url(
    user_service: UserService,
    sample_user: User,
) -> None:
    url = "https://res.cloudinary.com/demo/image/upload/v1/fluentmeet/avatars/abc.jpg"
    updated = user_service.update_avatar_url(sample_user, url)
    assert updated.avatar_url == url


# ── soft_delete_user ──────────────────────────────────────────────────


def test_soft_delete_sets_deleted_at_and_deactivates(
    user_service: UserService,
    sample_user: User,
    db_session: Session,
) -> None:
    assert sample_user.deleted_at is None
    assert sample_user.is_active is True

    user_service.soft_delete_user(sample_user)

    refreshed = db_session.execute(
        select(User).where(User.id == sample_user.id)
    ).scalar_one()
    assert refreshed.deleted_at is not None
    assert refreshed.is_active is False


# ── hard_delete_user ──────────────────────────────────────────────────


def test_hard_delete_removes_user_and_tokens(
    user_service: UserService,
    sample_user: User,
    db_session: Session,
) -> None:
    # Create a verification token for the user.
    token = VerificationToken(
        user_id=sample_user.id,
        token=str(uuid.uuid4()),
        expires_at=datetime.now(UTC),
    )
    db_session.add(token)
    db_session.commit()

    user_service.hard_delete_user(sample_user)

    # User should be gone.
    assert (
        db_session.execute(
            select(User).where(User.id == sample_user.id)
        ).scalar_one_or_none()
        is None
    )
    # Token should be gone.
    assert (
        db_session.execute(
            select(VerificationToken).where(
                VerificationToken.user_id == sample_user.id
            )
        ).scalar_one_or_none()
        is None
    )
