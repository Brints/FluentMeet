from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.crud.user.user import create_user
from app.crud.verification_token import verification_token_repository
from app.models.user import Base
from app.models.verification_token import VerificationToken
from app.schemas.user import SupportedLanguage, UserCreate


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _new_user_payload(email: str) -> UserCreate:
    return UserCreate(
        email=email,
        password="MyStr0ngP@ss!",
        full_name="Token User",
        speaking_language=SupportedLanguage.ENGLISH,
        listening_language=SupportedLanguage.FRENCH,
    )


def _create_user(db: Session, email: str) -> int:
    user = create_user(db=db, user_in=_new_user_payload(email=email))
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


def test_create_token_persists_token(db_session: Session) -> None:
    user_id = _create_user(db=db_session, email="crud-create@example.com")
    token = verification_token_repository.create_token(db=db_session, user_id=user_id)

    assert token.id is not None
    assert token.user_id == user_id
    assert token.token
    assert _as_aware_utc(token.expires_at) > datetime.now(UTC)


def test_get_token_returns_matching_row(db_session: Session) -> None:
    user_id = _create_user(db=db_session, email="crud-get@example.com")
    created = verification_token_repository.create_token(db=db_session, user_id=user_id)

    found = verification_token_repository.get_token(db=db_session, token=created.token)

    assert found is not None
    assert found.id == created.id


def test_delete_token_removes_row(db_session: Session) -> None:
    user_id = _create_user(db=db_session, email="crud-delete@example.com")
    created = verification_token_repository.create_token(db=db_session, user_id=user_id)

    verification_token_repository.delete_token(db=db_session, token_id=created.id)

    statement = select(VerificationToken).where(VerificationToken.id == created.id)
    assert db_session.execute(statement).scalar_one_or_none() is None


def test_delete_unexpired_tokens_for_user_keeps_expired_tokens(
    db_session: Session,
) -> None:
    user_id = _create_user(db=db_session, email="crud-prune@example.com")
    token = verification_token_repository.create_token(db=db_session, user_id=user_id)
    _force_token_expiry(db=db_session, token_id=token.id)
    second = verification_token_repository.create_token(db=db_session, user_id=user_id)

    verification_token_repository.delete_unexpired_tokens_for_user(
        db=db_session,
        user_id=user_id,
    )

    assert (
        verification_token_repository.get_token(db=db_session, token=second.token)
        is None
    )
    assert (
        verification_token_repository.get_token(db=db_session, token=token.token)
        is not None
    )
