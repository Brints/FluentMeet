import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.crud.user import create_user, get_user_by_email
from app.db.session import get_db
from app.schemas.auth import (
    ActionAcknowledgement,
    ForgotPasswordRequest,
    SignupResponse,
)
from app.schemas.user import UserCreate
from app.services.email_producer import EmailProducerService, get_email_producer_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])
DB_SESSION_DEPENDENCY = Depends(get_db)
EMAIL_PRODUCER_DEPENDENCY = Depends(get_email_producer_service)


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
)
async def signup(
    user_in: UserCreate,
    db: Session = DB_SESSION_DEPENDENCY,
    email_producer: EmailProducerService = EMAIL_PRODUCER_DEPENDENCY,
) -> SignupResponse:
    user = create_user(db=db, user_in=user_in)

    verification_link = (
        f"{settings.FRONTEND_BASE_URL}/verify-email?user={user.id}&token={uuid4()}"
    )
    try:
        await email_producer.send_email(
            to=user.email,
            subject="Verify your FluentMeet account",
            html_body=None,
            template_data={"verification_link": verification_link},
            template="verification",
        )
    except Exception as exc:
        # Signup should succeed even if email queueing fails.
        logger.warning(
            "Failed to enqueue verification email for user %s: %s", user.id, exc
        )

    return SignupResponse.model_validate(user)


@router.post(
    "/forgot-password",
    response_model=ActionAcknowledgement,
    status_code=status.HTTP_202_ACCEPTED,
)
async def forgot_password(
    request: ForgotPasswordRequest,
    db: Session = DB_SESSION_DEPENDENCY,
    email_producer: EmailProducerService = EMAIL_PRODUCER_DEPENDENCY,
) -> ActionAcknowledgement:
    user = get_user_by_email(db, request.email)

    if user:
        reset_link = (
            f""
            f"{settings.FRONTEND_BASE_URL}/reset-password?user={user.id}"
            f"&token={uuid4()}"
        )
        try:
            await email_producer.send_email(
                to=user.email,
                subject="Reset your FluentMeet password",
                html_body=None,
                template_data={"reset_link": reset_link},
                template="password_reset",
            )
        except Exception as exc:
            logger.warning(
                "Failed to enqueue password reset email for %s: %s", user.email, exc
            )

    return ActionAcknowledgement(
        message=(
            "If an account with that email exists, we have sent "
            "password reset instructions."
        )
    )
