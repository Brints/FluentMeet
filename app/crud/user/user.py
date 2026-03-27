from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictException
from app.core.security import security_service
from app.models.user import User
from app.schemas.user import UserCreate


def get_user_by_email(db: Session, email: str) -> User | None:
    statement = select(User).where(User.email == email.lower())
    return db.execute(statement).scalar_one_or_none()


def create_user(db: Session, user_in: UserCreate) -> User:
    existing_user = get_user_by_email(db, user_in.email)
    if existing_user:
        raise ConflictException(
            code="EMAIL_ALREADY_REGISTERED",
            message="An account with this email already exists.",
        )

    db_user = User(
        email=user_in.email.lower(),
        hashed_password=security_service.hash_password(user_in.password),
        full_name=user_in.full_name,
        speaking_language=user_in.speaking_language.value,
        listening_language=user_in.listening_language.value,
        is_active=True,
        is_verified=False,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user
