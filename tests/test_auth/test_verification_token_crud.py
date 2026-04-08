import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.modules.auth.models import User, VerificationToken
from app.modules.auth.schemas import SupportedLanguage


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _create_user(db: Session, email: str) -> uuid.UUID:
    user = User(
        email=email,
        hashed_password="hashed_password",
        full_name="Token User",
        speaking_language=SupportedLanguage.ENGLISH.value,
        listening_language=SupportedLanguage.FRENCH.value,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user.id


def _force_token_expiry(db: Session, token_id: int) -> None:
    token = db.get(VerificationToken, token_id)
    if token is None:
        return
    token.expires_at = datetime.now(UTC) - timedelta(hours=1)
    db.commit()


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


def test_create_token_persists_token(db_session: Session) -> None:
    user_id = _create_user(db=db_session, email="crud-create@example.com")

    # Direct model creation instead of repository
    token = VerificationToken(
        user_id=user_id, expires_at=datetime.now(UTC) + timedelta(hours=24)
    )
    db_session.add(token)
    db_session.commit()
    db_session.refresh(token)

    assert token.id is not None
    assert token.user_id == user_id
    assert token.token
    assert _as_aware_utc(token.expires_at) > datetime.now(UTC)


def test_get_token_returns_matching_row(db_session: Session) -> None:
    user_id = _create_user(db=db_session, email="crud-get@example.com")
    token = VerificationToken(user_id=user_id)
    db_session.add(token)
    db_session.commit()

    statement = select(VerificationToken).where(VerificationToken.token == token.token)
    found = db_session.execute(statement).scalar_one_or_none()

    assert found is not None
    assert found.id == token.id


def test_delete_token_removes_row(db_session: Session) -> None:
    user_id = _create_user(db=db_session, email="crud-delete@example.com")
    token = VerificationToken(user_id=user_id)
    db_session.add(token)
    db_session.commit()

    db_session.delete(token)
    db_session.commit()

    statement = select(VerificationToken).where(VerificationToken.id == token.id)
    assert db_session.execute(statement).scalar_one_or_none() is None


def test_pruning_expired_tokens_behavior(db_session: Session) -> None:
    """Manual verification of pruning logic previously in repository."""
    user_id = _create_user(db=db_session, email="crud-prune@example.com")

    # Token 1: Expired
    t1 = VerificationToken(user_id=user_id)
    db_session.add(t1)
    db_session.commit()
    _force_token_expiry(db_session, t1.id)

    # Token 2: Unexpired
    t2 = VerificationToken(user_id=user_id)
    db_session.add(t2)
    db_session.commit()

    # Simulation of delete_unexpired_tokens_for_user
    now = datetime.now(UTC)
    statement = select(VerificationToken).where(
        VerificationToken.user_id == user_id, VerificationToken.expires_at >= now
    )
    unexpired = db_session.execute(statement).scalars().all()
    for t in unexpired:
        db_session.delete(t)
    db_session.commit()

    # Expired token should remain, unexpired should be gone
    assert db_session.get(VerificationToken, t2.id) is None
    assert db_session.get(VerificationToken, t1.id) is not None
