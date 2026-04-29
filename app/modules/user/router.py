"""User API Router module.

Registers the public FastApi routes mapping stateless token schemas against
profile handling logic layers locally reliably mapped explicitly.
"""

import logging

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.external_services.cloudinary.constants import RESOURCE_TYPE_IMAGE
from app.external_services.cloudinary.service import (
    StorageService,
    get_storage_service,
)
from app.modules.auth.models import User
from app.modules.auth.token_store import TokenStoreService, get_token_store_service
from app.modules.user.constants import (
    AVATAR_FOLDER,
    MSG_ACCOUNT_DELETED,
    MSG_ACCOUNT_SOFT_DELETED,
    MSG_AVATAR_UPLOADED,
    MSG_PROFILE_RETRIEVED,
    MSG_PROFILE_UPDATED,
)
from app.modules.user.dependencies import get_user_service
from app.modules.user.schemas import (
    AvatarUploadResponse,
    DeleteResponse,
    ProfileApiResponse,
    UserProfileResponse,
    UserUpdate,
)
from app.modules.user.service import UserService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/me",
    response_model=ProfileApiResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current user profile",
    description="Returns the authenticated user's full public profile.",
)
async def get_profile(
    current_user: User = Depends(get_current_user),
) -> ProfileApiResponse:
    return ProfileApiResponse(
        message=MSG_PROFILE_RETRIEVED,
        data=UserProfileResponse.model_validate(current_user),
    )


@router.patch(
    "/me",
    response_model=ProfileApiResponse,
    status_code=status.HTTP_200_OK,
    summary="Update current user profile",
    description=(
        "Accepts a JSON body with optional fields (full_name, "
        "speaking_language, listening_language). Only provided fields "
        "are updated."
    ),
)
async def update_profile(
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service),
) -> ProfileApiResponse:
    update_data = payload.model_dump(exclude_unset=True)

    if update_data:
        # Convert SupportedLanguage enum values to plain strings for ORM.
        for lang_field in ("speaking_language", "listening_language"):
            if lang_field in update_data and update_data[lang_field] is not None:
                update_data[lang_field] = str(update_data[lang_field].value)

        current_user = user_service.update_user(current_user, update_data)

    return ProfileApiResponse(
        message=MSG_PROFILE_UPDATED,
        data=UserProfileResponse.model_validate(current_user),
    )


@router.post(
    "/me/avatar",
    response_model=AvatarUploadResponse,
    status_code=status.HTTP_200_OK,
    summary="Upload or replace profile avatar",
    description=(
        "Accepts a multipart/form-data request with an `avatar` file "
        "(JPEG, PNG, or WebP; max 5 MB). The old avatar is deleted "
        "from cloud storage before uploading the new one."
    ),
)
async def upload_avatar(
    avatar: UploadFile = File(..., description="Avatar image file"),
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service),
    storage_service: StorageService = Depends(get_storage_service),
) -> AvatarUploadResponse:
    # Delete old avatar if one exists.
    if current_user.avatar_url:
        old_public_id = _extract_public_id(current_user.avatar_url)
        if old_public_id:
            try:
                await storage_service.delete_asset(
                    old_public_id, resource_type=RESOURCE_TYPE_IMAGE
                )
            except Exception as exc:
                logger.warning(
                    f"Failed to delete old avatar for user %s — continuing. {exc}",
                    current_user.id,
                )

    # Upload new avatar.
    result = await storage_service.upload_image(
        file=avatar,
        folder=AVATAR_FOLDER,
        public_id=str(current_user.id),
        transformation={"width": 400, "height": 400, "crop": "fill", "gravity": "face"},
    )

    updated_user = user_service.update_avatar_url(current_user, result.secure_url)

    return AvatarUploadResponse(
        message=MSG_AVATAR_UPLOADED,
        data=UserProfileResponse.model_validate(updated_user),
    )


@router.delete(
    "/me",
    response_model=DeleteResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete current user account",
    description=(
        "Soft-deletes the account by default. Pass `?hard=true` for "
        "permanent deletion (GDPR Right to Erasure). In both cases "
        "all active sessions are invalidated."
    ),
)
async def delete_account(
    request: Request,
    hard: bool = Query(
        default=False,
        description="Set to true for permanent account deletion.",
    ),
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(get_user_service),
    token_store: TokenStoreService = Depends(get_token_store_service),
    storage_service: StorageService = Depends(get_storage_service),
) -> JSONResponse:
    # ── 1. Perform DB operation ───────────────────────────────────────
    if hard:
        # Delete avatar from cloud storage before wiping the row.
        if current_user.avatar_url:
            old_public_id = _extract_public_id(current_user.avatar_url)
            if old_public_id:
                try:
                    await storage_service.delete_asset(
                        old_public_id, resource_type=RESOURCE_TYPE_IMAGE
                    )
                except Exception as exc:
                    logger.warning(
                        f"Failed to delete avatar during hard-delete for user %s {exc}",
                        current_user.id,
                    )

        user_service.hard_delete_user(current_user)
        message = MSG_ACCOUNT_DELETED
    else:
        user_service.soft_delete_user(current_user)
        message = MSG_ACCOUNT_SOFT_DELETED

    # ── 2. Session teardown ───────────────────────────────────────────
    # Revoke all refresh tokens for this user.
    await token_store.revoke_all_user_tokens(current_user.email)

    # Blacklist the current access token's JTI.
    access_token = _extract_bearer_token(request)
    if access_token:
        from jose import jwt as jose_jwt

        try:
            payload = jose_jwt.decode(
                access_token,
                settings.SECRET_KEY,
                algorithms=[settings.ALGORITHM],
            )
            jti = payload.get("jti")
            if jti:
                remaining = int(payload.get("exp", 0) - __import__("time").time())
                await token_store.blacklist_access_token(jti, max(remaining, 0))
        except Exception as exc:
            logger.warning(f"Failed to revoke access token: {exc}")
            pass  # best-effort

    # ── 3. Build response & clear cookie ──────────────────────────────
    body = DeleteResponse(status="ok", message=message)
    response = JSONResponse(
        content=body.model_dump(),
        status_code=status.HTTP_200_OK,
    )
    response.delete_cookie(
        key="refresh_token",
        path=f"{settings.API_V1_STR}/auth",
        httponly=True,
        secure=True,
        samesite="strict",
    )
    return response


# ── Helpers ───────────────────────────────────────────────────────────


def _extract_public_id(secure_url: str) -> str | None:
    """Derive the Cloudinary public ID from a secure URL.

    Example input:
        https://res.cloudinary.com/demo/image/upload/v1234/fluentmeet/avatars/abc.jpg

    Args:
        secure_url (str): Remote CDN tracking path safely bounded statically
            natively seamlessly dynamically mapped seamlessly natively.

    Returns:
        str | None: Result correctly tracking bounds seamlessly accurately
            dynamically securely gracefully gracefully smoothly seamlessly
            automatically natively explicitly cleanly softly safely reliably.
    """
    try:
        # Strip the version segment and file extension.
        parts = secure_url.split("/upload/")
        if len(parts) != 2:
            return None
        path = parts[1]
        # Remove the version prefix (e.g. "v1234/").
        if path.startswith("v") and "/" in path:
            path = path.split("/", 1)[1]
        # Remove file extension.
        dot_idx = path.rfind(".")
        if dot_idx != -1:
            path = path[:dot_idx]
        return path
    except Exception as exc:
        logger.warning(f"Failed to extract public ID from secure URL: {exc}")
        return None


def _extract_bearer_token(request: Request) -> str | None:
    """Pull the raw JWT from the ``Authorization: Bearer …`` header.

    Args:
        request (Request): The core FastAPI payload injection gracefully
            intuitively automatically explicitly.

    Returns:
        str | None: Raw JWT value effectively seamlessly correctly natively.
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None
