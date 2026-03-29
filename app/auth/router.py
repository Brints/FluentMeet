import logging

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse

from app.auth.dependencies import get_auth_service, get_auth_verification_service
from app.auth.schemas import (
    ActionAcknowledgement,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    RefreshTokenResponse,
    ResendVerificationRequest,
    SignupRequest,
    SignupResponse,
    VerifyEmailResponse,
)
from app.auth.service import AuthService
from app.auth.verification import AuthVerificationService
from app.core.config import settings
from app.core.rate_limiter import limiter
from app.core.sanitize import sanitize_log_args

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def signup(
    user_in: SignupRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> SignupResponse:
    user = await auth_service.signup(
        user_in=user_in,
        frontend_base_url=settings.FRONTEND_BASE_URL,
    )
    return SignupResponse.model_validate(user)


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate a registered user",
    description=(
        "Validates email and password, issues a JWT access token (returned "
        "in the body) and a JWT refresh token (set as an HttpOnly cookie). "
        "Rate-limited to 10 requests/minute per IP. The account is locked "
        "after 5 consecutive failed attempts for 5 days."
    ),
    responses={
        401: {"description": "Invalid credentials"},
        403: {"description": "Account not verified, deleted, or locked"},
    },
)
@limiter.limit("10/minute")
async def login(
    request: Request,
    payload: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> JSONResponse:
    del request  # consumed by slowapi

    login_response, refresh_token, refresh_ttl = await auth_service.login(payload)

    response = JSONResponse(
        content=login_response.model_dump(mode="json"), status_code=200
    )

    # Set HttpOnly refresh-token cookie
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="strict",
        path=f"{settings.API_V1_STR}/auth",
        max_age=refresh_ttl,
    )

    return response


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
        }
    },
)
def verify_email(
    token: str | None = Query(default=None),
    auth_verification_service: AuthVerificationService = Depends(
        get_auth_verification_service
    ),
) -> VerifyEmailResponse:
    auth_verification_service.verify_email(token=token)
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
    auth_verification_service: AuthVerificationService = Depends(
        get_auth_verification_service
    ),
) -> ActionAcknowledgement:
    del request
    try:
        await auth_verification_service.resend_verification_email(
            email=str(payload.email),
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
            "If an account with that email exists, we have sent a verification email."
        )
    )


@router.post(
    "/forgot-password",
    response_model=ActionAcknowledgement,
    status_code=status.HTTP_202_ACCEPTED,
)
async def forgot_password(
    request: ForgotPasswordRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> ActionAcknowledgement:
    await auth_service.forgot_password(
        email=str(request.email),
        frontend_base_url=settings.FRONTEND_BASE_URL,
    )
    return ActionAcknowledgement(
        message=(
            "If an account with that email exists, we have sent "
            "password reset instructions."
        )
    )


@router.post(
    "/refresh-token",
    response_model=RefreshTokenResponse,
    summary="Rotate refresh token",
    description=(
        "Reads the ``refresh_token`` HttpOnly cookie, validates it, revokes the "
        "old JTI, and issues a new access + refresh token pair. Implements the "
        "**Refresh Token Rotation** pattern: reuse of a revoked token triggers "
        "full session invalidation."
    ),
    status_code=200,
    responses={
        200: {"description": "New access token issued; refresh cookie updated."},
        401: {"description": "Missing, invalid, expired, or reused refresh token."},
        403: {"description": "Account has been deactivated or deleted."},
    },
)
@limiter.limit("30/minute")
async def refresh_token(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
) -> JSONResponse:
    # --- 1. Read the cookie --------------------------------------------------
    raw_token = request.cookies.get("refresh_token")
    if not raw_token:
        from app.core.exceptions import UnauthorizedException

        raise UnauthorizedException(
            code="MISSING_REFRESH_TOKEN",
            message="No refresh token provided.",
        )

    body, new_refresh_token, new_ttl = await auth_service.refresh_token(raw_token)

    response = JSONResponse(content=body.model_dump(mode="json"), status_code=200)
    response.set_cookie(
        key="refresh_token",
        value=new_refresh_token,
        httponly=True,
        secure=True,
        samesite="strict",
        path=f"{settings.API_V1_STR}/auth",
        max_age=new_ttl,
    )
    return response
