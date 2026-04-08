"""Global FastAPI dependencies shared across feature packages.

The ``get_current_user`` dependency lives here so that any package
(``auth``, ``user``, ``rooms``, …) can protect its endpoints without
circular imports.
"""

import logging

from fastapi import Depends
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
    OAuth2PasswordBearer,
)
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.db.session import get_db
from app.modules.auth.models import User
from app.modules.auth.token_store import TokenStoreService, get_token_store_service

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login",
)
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    bearer: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
    token_store: TokenStoreService = Depends(get_token_store_service),
) -> User:
    """Decode an access-token JWT and return the authenticated user.

    Guards
    ------
    - Missing token          →  401
    - Invalid / expired JWT  →  401
    - Blacklisted JTI        →  401
    - User not found          →  401
    - Account soft-deleted    →  403
    - Account deactivated     →  403

    Returns
    -------
    The :class:`~app.auth.models.User` ORM instance.
    """
    # Prefer Bearer token if provided (e.g. from 'HTTP Bearer' field in Swagger)
    # otherwise fall back to OAuth2 token (from 'Authorize' login form).
    final_token = bearer.credentials if bearer else token

    if not final_token:
        raise UnauthorizedException(
            code="MISSING_TOKEN",
            message="Not authenticated",
        )

    credentials_exc = UnauthorizedException(
        code="INVALID_CREDENTIALS",
        message="Could not validate credentials.",
    )

    # ── 1. Decode JWT ─────────────────────────────────────────────────
    try:
        payload = jwt.decode(
            final_token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
    except JWTError as err:
        raise credentials_exc from err

    email: str | None = payload.get("sub")
    jti: str | None = payload.get("jti")
    token_type: str | None = payload.get("type")

    if not email or not jti or token_type != "access":
        raise credentials_exc

    # ── 2. Check blacklist ────────────────────────────────────────────
    if await token_store.is_access_token_blacklisted(jti):
        raise UnauthorizedException(
            code="TOKEN_REVOKED",
            message="This token has been revoked.",
        )

    # ── 3. Load user from DB ─────────────────────────────────────────
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()

    if user is None:
        raise credentials_exc

    # ── 4. Account-state guards ───────────────────────────────────────
    if user.deleted_at is not None:
        raise ForbiddenException(
            code="ACCOUNT_DELETED",
            message="This account has been deleted.",
        )

    if not user.is_active:
        raise ForbiddenException(
            code="ACCOUNT_DEACTIVATED",
            message="This account has been deactivated.",
        )

    return user


oauth2_scheme_optional = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login",
    auto_error=False,
)


async def get_current_user_optional(
    token: str | None = Depends(oauth2_scheme_optional),
    bearer: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
    token_store: TokenStoreService = Depends(get_token_store_service),
) -> User | None:
    """Attempt to decode JWT and return User if present, otherwise return None."""
    try:
        user = await get_current_user(
            token=token, bearer=bearer, db=db, token_store=token_store
        )
        return user
    except UnauthorizedException:
        # Happens if token is missing or generic Invalid Credentials
        return None
    except ForbiddenException:
        # Happens if account is deleted or deactivated. Could also return None.
        return None
