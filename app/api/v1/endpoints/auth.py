import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limiter import limiter
from app.core.sanitize import sanitize_log_args
from app.crud.user.user import create_user, get_user_by_email
from app.db.session import get_db
from app.schemas.auth import (
    ActionAcknowledgement,
    ForgotPasswordRequest,
    ResendVerificationRequest,
    SignupResponse,
    VerifyEmailResponse,
)
from app.schemas.user import UserCreate
from app.services.auth_verification import (
    AuthVerificationService,
    get_auth_verification_service,
)
from app.services.email_producer import EmailProducerService, get_email_producer_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])
DB_SESSION_DEPENDENCY = Depends(get_db)
EMAIL_PRODUCER_DEPENDENCY = Depends(get_email_producer_service)
AUTH_VERIFICATION_SERVICE_DEPENDENCY = Depends(get_auth_verification_service)


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
)
async def signup(
    user_in: UserCreate,
    db: Session = DB_SESSION_DEPENDENCY,
    email_producer: EmailProducerService = EMAIL_PRODUCER_DEPENDENCY,
    auth_verification_service: AuthVerificationService = (
        AUTH_VERIFICATION_SERVICE_DEPENDENCY
    ),
) -> SignupResponse:
    user = create_user(db=db, user_in=user_in)
    verification_token = auth_verification_service.create_verification_token(
        db=db,
        user_id=user.id,
    )

    verification_link = (
        f"{settings.FRONTEND_BASE_URL}/verify-email?token={verification_token.token}"
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
        user_id_safe, exc_safe = sanitize_log_args(user.id, exc)
        logger.warning(
            "Failed to enqueue verification email for user %s: %s",
            user_id_safe,
            exc_safe,
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
            email_safe, exc_safe = sanitize_log_args(user.email, exc)
            logger.warning(
                "Failed to enqueue password reset email for %s: %s",
                email_safe,
                exc_safe,
            )

    return ActionAcknowledgement(
        message=(
            "If an account with that email exists, we have sent "
            "password reset instructions."
        )
    )


@router.get(
    "/verify-email",
    response_model=VerifyEmailResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify user email address",
    description=(
        "Validates an email verification token, activates the user account, "
        "and invalidates the token."
    ),
    responses={
        400: {
            "description": "Missing, invalid, or expired token",
            "content": {
                "application/json": {
                    "examples": {
                        "missing": {
                            "value": {
                                "status": "error",
                                "code": "MISSING_TOKEN",
                                "message": "Verification token is required.",
                                "details": [],
                            }
                        },
                        "invalid": {
                            "value": {
                                "status": "error",
                                "code": "INVALID_TOKEN",
                                "message": "Verification token is invalid.",
                                "details": [],
                            }
                        },
                        "expired": {
                            "value": {
                                "status": "error",
                                "code": "TOKEN_EXPIRED",
                                "message": (
                                    "Verification token has expired. "
                                    "Please request a new one."
                                ),
                                "details": [],
                            }
                        },
                    }
                }
            },
        }
    },
)
def verify_email(
    token: str | None = Query(default=None),
    db: Session = DB_SESSION_DEPENDENCY,
    auth_verification_service: AuthVerificationService = (
        AUTH_VERIFICATION_SERVICE_DEPENDENCY
    ),
) -> VerifyEmailResponse:
    auth_verification_service.verify_email(db=db, token=token)
    return VerifyEmailResponse(
        message="Email successfully verified. You can now log in.",
    )


@router.post(
    "/resend-verification",
    response_model=ActionAcknowledgement,
    status_code=status.HTTP_200_OK,
    summary="Resend email verification link",
    description=(
        "Queues a new verification email when the account exists and is not "
        "verified. Always returns a generic response to prevent user enumeration."
    ),
)
@limiter.limit("3/minute")
async def resend_verification(
    request: Request,
    payload: ResendVerificationRequest,
    db: Session = DB_SESSION_DEPENDENCY,
    email_producer: EmailProducerService = EMAIL_PRODUCER_DEPENDENCY,
    auth_verification_service: AuthVerificationService = (
        AUTH_VERIFICATION_SERVICE_DEPENDENCY
    ),
) -> ActionAcknowledgement:
    del request
    try:
        await auth_verification_service.resend_verification_email(
            db=db,
            email=str(payload.email),
            email_producer=email_producer,
        )
    except Exception as exc:
        email_safe, exc_safe = sanitize_log_args(payload.email, exc)
        logger.warning(
            "Failed to enqueue verification resend for %s: %s",
            email_safe,
            exc_safe,
        )

    return ActionAcknowledgement(
        message=(
            "If an account with that email exists, we have sent a verification "
            "email."
        )
    )
