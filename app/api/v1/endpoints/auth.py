import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.core.rate_limiter import limiter
from app.core.sanitize import sanitize_log_args
from app.core.security import SecurityService, get_security_service
from app.crud.user.user import create_user, get_user_by_email
from app.db.session import get_db
from app.schemas.auth import (
    ActionAcknowledgement,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    RefreshTokenResponse,
    ResendVerificationRequest,
    SignupResponse,
    VerifyEmailResponse,
)
from app.schemas.user import UserCreate
from app.services.account_lockout import (
    AccountLockoutService,
    get_account_lockout_service,
)
from app.services.auth_verification import (
    AuthVerificationService,
    get_auth_verification_service,
)
from app.services.email_producer import EmailProducerService, get_email_producer_service
from app.services.token_store import TokenStoreService, get_token_store_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])
DB_SESSION_DEPENDENCY = Depends(get_db)
EMAIL_PRODUCER_DEPENDENCY = Depends(get_email_producer_service)
AUTH_VERIFICATION_SERVICE_DEPENDENCY = Depends(get_auth_verification_service)
SECURITY_SERVICE_DEPENDENCY = Depends(get_security_service)
TOKEN_STORE_SERVICE_DEPENDENCY = Depends(get_token_store_service)
ACCOUNT_LOCKOUT_SERVICE_DEPENDENCY = Depends(get_account_lockout_service)


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
            "If an account with that email exists, we have sent a verification email."
        )
    )


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
        401: {
            "description": "Invalid credentials",
            "content": {
                "application/json": {
                    "example": {
                        "status": "error",
                        "code": "INVALID_CREDENTIALS",
                        "message": "Invalid email or password.",
                        "details": [],
                    }
                }
            },
        },
        403: {
            "description": "Account not verified, deleted, or locked",
            "content": {
                "application/json": {
                    "examples": {
                        "not_verified": {
                            "value": {
                                "status": "error",
                                "code": "EMAIL_NOT_VERIFIED",
                                "message": (
                                    "Please verify your email before logging in."
                                ),
                                "details": [],
                            }
                        },
                        "deleted": {
                            "value": {
                                "status": "error",
                                "code": "ACCOUNT_DELETED",
                                "message": "This account has been deleted.",
                                "details": [],
                            }
                        },
                        "locked": {
                            "value": {
                                "status": "error",
                                "code": "ACCOUNT_LOCKED",
                                "message": (
                                    "Account is temporarily locked due to "
                                    "too many failed login attempts. "
                                    "Please try again later."
                                ),
                                "details": [],
                            }
                        },
                    }
                }
            },
        },
    },
)
@limiter.limit("10/minute")
async def login(
    request: Request,
    payload: LoginRequest,
    db: Session = DB_SESSION_DEPENDENCY,
    security_svc: SecurityService = SECURITY_SERVICE_DEPENDENCY,
    token_store: TokenStoreService = TOKEN_STORE_SERVICE_DEPENDENCY,
    lockout_svc: AccountLockoutService = ACCOUNT_LOCKOUT_SERVICE_DEPENDENCY,
) -> JSONResponse:
    del request  # consumed by slowapi
    email = payload.email.lower()

    # Check lockout
    if await lockout_svc.is_locked(email):
        raise ForbiddenException(
            code="ACCOUNT_LOCKED",
            message=(
                "Account is temporarily locked due to too many failed "
                "login attempts. Please try again later."
            ),
        )

    # Lookup user
    user = get_user_by_email(db, email)
    if user is None:
        # Record a failed attempt even for non-existent emails so that
        # timing is indistinguishable from a wrong-password attempt.
        await lockout_svc.record_failed_attempt(email)
        raise UnauthorizedException(
            code="INVALID_CREDENTIALS",
            message="Invalid email or password.",
        )

    # Verify password
    if not security_svc.verify_password(payload.password, user.hashed_password):
        await lockout_svc.record_failed_attempt(email)
        raise UnauthorizedException(
            code="INVALID_CREDENTIALS",
            message="Invalid email or password.",
        )

    # Guard: email verified?
    if not user.is_verified:
        raise ForbiddenException(
            code="EMAIL_NOT_VERIFIED",
            message="Please verify your email before logging in.",
        )

    # Guard: soft-deleted?
    if user.deleted_at is not None:
        raise ForbiddenException(
            code="ACCOUNT_DELETED",
            message="This account has been deleted.",
        )

    # Reset failed-login counter on success
    await lockout_svc.reset_attempts(email)

    # Issue tokens
    access_token, expires_in = security_svc.create_access_token(email=email)
    refresh_token, refresh_jti, refresh_ttl = security_svc.create_refresh_token(
        email=email,
    )

    # Persist refresh JTI in Redis (keyed by email + jti)
    await token_store.save_refresh_token(
        email=email, jti=refresh_jti, ttl_seconds=refresh_ttl
    )

    # Build JSON body
    body = LoginResponse(
        access_token=access_token,
        user_id=user.id,
        token_type="bearer",
        expires_in=expires_in,
    )

    response = JSONResponse(content=body.model_dump(mode="json"), status_code=200)

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


@router.post(
    "/refresh-token",
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
        401: {
            "description": "Missing, invalid, expired, or reused refresh token.",
            "content": {
                "application/json": {
                    "examples": {
                        "missing": {
                            "value": {
                                "status": "error",
                                "code": "MISSING_REFRESH_TOKEN",
                                "message": "No refresh token provided.",
                                "details": [],
                            }
                        },
                        "invalid": {
                            "value": {
                                "status": "error",
                                "code": "INVALID_REFRESH_TOKEN",
                                "message": "Refresh token is invalid or has expired.",
                                "details": [],
                            }
                        },
                        "reuse": {
                            "value": {
                                "status": "error",
                                "code": "REFRESH_TOKEN_REUSE",
                                "message": (
                                    "Session has been invalidated. Please log in again."
                                ),
                                "details": [],
                            }
                        },
                    }
                }
            },
        },
        403: {
            "description": "Account has been deactivated or deleted.",
            "content": {
                "application/json": {
                    "examples": {
                        "deactivated": {
                            "value": {
                                "status": "error",
                                "code": "ACCOUNT_DEACTIVATED",
                                "message": "This account has been deactivated.",
                                "details": [],
                            }
                        }
                    }
                }
            },
        },
    },
)
@limiter.limit("30/minute")
async def refresh_token(
    request: Request,
    db: Session = DB_SESSION_DEPENDENCY,
    security_svc: SecurityService = SECURITY_SERVICE_DEPENDENCY,
    token_store: TokenStoreService = TOKEN_STORE_SERVICE_DEPENDENCY,
) -> JSONResponse:
    # --- 1. Read the cookie --------------------------------------------------
    raw_token = request.cookies.get("refresh_token")
    if not raw_token:
        raise UnauthorizedException(
            code="MISSING_REFRESH_TOKEN",
            message="No refresh token provided.",
        )

    # --- 2. Decode & validate signature / expiry / type ----------------------
    try:
        token_data = security_svc.decode_refresh_token(raw_token)
    except ValueError as exc:
        raise UnauthorizedException(
            code="INVALID_REFRESH_TOKEN",
            message="Refresh token is invalid or has expired.",
        ) from exc

    # RefreshTokenClaims guarantees email and jti are non-None str.
    email = token_data.email
    old_jti = token_data.jti

    # --- 3. Check Redis — detect reuse of a revoked token --------------------
    if not await token_store.is_refresh_token_valid(email=email, jti=old_jti):
        # Potential theft: tear down ALL sessions for this user.
        await token_store.revoke_all_user_tokens(email=email)
        logger.warning(
            "Refresh token reuse detected for %s — all sessions revoked.",
            sanitize_log_args(email)[0],
        )
        raise UnauthorizedException(
            code="REFRESH_TOKEN_REUSE",
            message="Session has been invalidated. Please log in again.",
        )

    # --- 4. Re-check account status ------------------------------------------
    user = get_user_by_email(db, email)
    if user is None or user.deleted_at is not None or not user.is_active:
        raise ForbiddenException(
            code="ACCOUNT_DEACTIVATED",
            message="This account has been deactivated.",
        )

    # --- 5. Rotation: revoke old JTI, issue new pair -------------------------
    await token_store.revoke_refresh_token(email=email, jti=old_jti)

    new_access_token, expires_in = security_svc.create_access_token(email=email)
    new_refresh_token, new_jti, new_ttl = security_svc.create_refresh_token(email=email)
    await token_store.save_refresh_token(email=email, jti=new_jti, ttl_seconds=new_ttl)

    # --- 6. Build response ---------------------------------------------------
    body = RefreshTokenResponse(
        access_token=new_access_token,
        token_type="bearer",
        expires_in=expires_in,
    )
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
