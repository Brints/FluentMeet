from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.verification_token import VerificationToken


class VerificationTokenRepository:
    def get_token(self, db: Session, token: str) -> VerificationToken | None:
        statement = select(VerificationToken).where(VerificationToken.token == token)
        return db.execute(statement).scalar_one_or_none()

    def create_token(self, db: Session, user_id: int) -> VerificationToken:
        expires_at = datetime.now(UTC) + timedelta(
            hours=settings.VERIFICATION_TOKEN_EXPIRE_HOURS
        )
        verification_token = VerificationToken(user_id=user_id, expires_at=expires_at)
        db.add(verification_token)
        db.commit()
        db.refresh(verification_token)
        return verification_token

    def delete_token(self, db: Session, token_id: int) -> None:
        token = db.get(VerificationToken, token_id)
        if token is None:
            return
        db.delete(token)
        db.commit()

    def delete_unexpired_tokens_for_user(self, db: Session, user_id: int) -> None:
        now = datetime.now(UTC)
        statement = select(VerificationToken).where(
            VerificationToken.user_id == user_id,
            VerificationToken.expires_at >= now,
        )
        tokens = db.execute(statement).scalars().all()
        for token in tokens:
            db.delete(token)
        if tokens:
            db.commit()


verification_token_repository = VerificationTokenRepository()


def get_token(db: Session, token: str) -> VerificationToken | None:
    return verification_token_repository.get_token(db=db, token=token)


def create_token(db: Session, user_id: int) -> VerificationToken:
    return verification_token_repository.create_token(db=db, user_id=user_id)


def delete_token(db: Session, token_id: int) -> None:
    verification_token_repository.delete_token(db=db, token_id=token_id)
