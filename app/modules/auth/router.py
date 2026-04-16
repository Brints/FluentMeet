"""Authentication API Router module.

Registers the public FastApi routes binding external endpoints logic mapping
securely against stateless token schemas locally.
"""

import logging
from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.core.rate_limiter import limiter
from app.core.sanitize import sanitize_log_args
from app.modules.auth.dependencies import (
    get_auth_service,
    get_auth_verification_service,
    get_google_oauth_service,
)
from app.modules.auth.models import User
from app.modules.auth.oauth_google import GoogleOAuthService
from app.modules.auth.schemas import (
    ActionAcknowledgement,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    RefreshTokenResponse,
    ResendVerificationRequest,
    ResetPasswordRequest,
    SignupRequest,
    SignupResponse,
    VerifyEmailResponse,
)
from app.modules.auth.service import AuthService
from app.modules.auth.verification import AuthVerificationService

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
    payload: LoginRequest | None = None,
    auth_service: AuthService = Depends(get_auth_service),
) -> JSONResponse:

    if payload is None:
        from app.core.exceptions import BadRequestException

        raise BadRequestException(
            code="MISSING_CREDENTIALS",
            message="Email and password are required.",
        )

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
    status_code=status.HTTP_200_OK,
)
@limiter.limit("5/minute")
async def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> ActionAcknowledgement:
    del request  # consumed by slowapi
    await auth_service.forgot_password(
        email=str(payload.email),
        frontend_base_url=settings.FRONTEND_BASE_URL,
    )
    return ActionAcknowledgement(
        message="If an account with this email exists, a password reset link has been sent.",  # noqa: E501
    )


@router.post(
    "/reset-password",
    response_model=ActionAcknowledgement,
    status_code=status.HTTP_200_OK,
    summary="Reset password using an email token",
    description=(
        "Validates a one-time reset token (from the forgot-password email), "
        "updates the user's password, deletes the token, and revokes all "
        "active sessions."
    ),
    responses={
        400: {"description": "Invalid or expired reset token, or same password."},
    },
)
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    payload: ResetPasswordRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> ActionAcknowledgement:
    del request  # consumed by slowapi
    await auth_service.reset_password(
        token=payload.token,
        new_password=payload.new_password,
    )
    return ActionAcknowledgement(
        message=(
            "Password has been reset successfully. Please log in with your new password."  # noqa: E501
        ),
    )


@router.post(
    "/change-password",
    response_model=ActionAcknowledgement,
    status_code=status.HTTP_200_OK,
    summary="Change password for the authenticated user",
    description=(
        "Verifies the current password, updates the hash, and revokes all "
        "active refresh tokens to force re-login on other devices."
    ),
    responses={
        400: {
            "description": (
                "Current password incorrect, or new password same as current."
            ),
        },
        401: {"description": "Not authenticated."},
    },
)
@limiter.limit("10/minute")
async def change_password(
    request: Request,
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> ActionAcknowledgement:
    del request  # consumed by slowapi
    await auth_service.change_password(
        user=current_user,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    return ActionAcknowledgement(
        message="Password updated successfully.",
    )


@router.post(
    "/logout",
    response_model=ActionAcknowledgement,
    status_code=status.HTTP_200_OK,
    summary="Log out the current session",
    description=(
        "Blacklists the current access token and revokes the refresh token, "
        "effectively terminating the session immediately."
    ),
    responses={
        401: {"description": "Not authenticated."},
    },
)
@limiter.limit("20/minute")
async def logout(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> ActionAcknowledgement:
    from jose import jwt as jose_jwt

    # --- Extract AT jti and remaining TTL from raw token -----------------
    auth_header = request.headers.get("authorization", "")
    raw_token = auth_header.removeprefix("Bearer ").strip()

    payload_data = jose_jwt.decode(
        raw_token,
        settings.SECRET_KEY,
        algorithms=[settings.ALGORITHM],
    )
    access_jti: str = payload_data["jti"]
    access_exp: int = payload_data["exp"]
    ttl_remaining = max(access_exp - int(datetime.now(UTC).timestamp()), 0)

    # --- Extract RT jti from cookie (optional) ---------------------------
    refresh_jti: str | None = None
    raw_rt = request.cookies.get("refresh_token")
    if raw_rt:
        try:
            rt_claims = jose_jwt.decode(
                raw_rt,
                settings.SECRET_KEY,
                algorithms=[settings.ALGORITHM],
            )
            refresh_jti = rt_claims.get("jti")
        except Exception:
            pass  # expired / malformed — ignore

    await auth_service.logout(
        email=current_user.email,
        access_jti=access_jti,
        access_ttl_remaining=ttl_remaining,
        refresh_jti=refresh_jti,
    )

    # Clear the HttpOnly refresh-token cookie
    response.delete_cookie(
        key="refresh_token",
        path=f"{settings.API_V1_STR}/auth",
    )

    return ActionAcknowledgement(
        message="Successfully logged out.",
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


@router.get(
    "/google/login",
    summary="Initiate Google OAuth 2.0 login flow",
    status_code=status.HTTP_302_FOUND,
)
async def google_login(
    google_oauth: GoogleOAuthService = Depends(get_google_oauth_service),
) -> RedirectResponse:
    import secrets

    from app.modules.auth.token_store import _get_redis_client

    state = secrets.token_urlsafe(32)
    redis = _get_redis_client()
    await redis.set(f"oauth_state:{state}", "1", ex=600)  # 10 minutes TTL

    url = google_oauth.build_auth_url(state=state)
    return RedirectResponse(url=url, status_code=302)


@router.get(
    "/google/callback",
    summary="Google OAuth 2.0 callback endpoint",
)
async def google_callback(
    code: str,
    state: str,
    google_oauth: GoogleOAuthService = Depends(get_google_oauth_service),
    auth_service: AuthService = Depends(get_auth_service),
) -> RedirectResponse:
    from app.core.exceptions import BadRequestException
    from app.modules.auth.token_store import _get_redis_client

    redis = _get_redis_client()
    state_key = f"oauth_state:{state}"

    # 1. State Validation
    if not await redis.exists(state_key):
        raise BadRequestException(
            code="INVALID_OAUTH_STATE",
            message="OAuth state is invalid or has expired.",
        )

    await redis.delete(state_key)

    # 2. Exchange Code & Get Profile
    access_token = await google_oauth.exchange_code(code=code)
    user_info = await google_oauth.get_user_info(access_token=access_token)

    email = user_info.get("email")
    if not email:
        raise BadRequestException(
            code="INVALID_OAUTH_PROFILE",
            message="Google account does not provide an email address.",
        )

    google_id = str(user_info.get("sub", ""))
    name = user_info.get("name")
    avatar = user_info.get("picture")

    # 3. Resolve user
    login_response, refresh_token, refresh_ttl = await auth_service.resolve_oauth_user(
        email=cast(str, email),
        google_id=google_id,
        name=name,
        avatar_url=avatar,
    )

    # 4. Return tokens (Cookie & Redirect with access token)
    # Using URL fragment as requested by the user
    redirect_url = (
        f"{settings.FRONTEND_BASE_URL}#access_token={login_response.access_token}"
    )
    response = RedirectResponse(url=redirect_url, status_code=302)

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
