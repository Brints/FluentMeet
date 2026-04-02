"""Pydantic schemas for the user feature package."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.auth.schemas import SupportedLanguage


# ── Request schemas ───────────────────────────────────────────────────


class UserUpdate(BaseModel):
    """Partial-update payload for ``PATCH /users/me``.

    Every field is optional — only the fields present in the request
    body are applied to the user record.
    """

    full_name: str | None = Field(default=None, max_length=255)
    speaking_language: SupportedLanguage | None = None
    listening_language: SupportedLanguage | None = None


# ── Response schemas ──────────────────────────────────────────────────


class UserProfileResponse(BaseModel):
    """Public-facing user profile — intentionally excludes
    ``hashed_password``, ``deleted_at``, and ``updated_at``.
    """

    id: uuid.UUID
    email: str
    full_name: str | None = None
    avatar_url: str | None = None
    speaking_language: str
    listening_language: str
    is_active: bool
    is_verified: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProfileApiResponse(BaseModel):
    """Standard envelope wrapping a ``UserProfileResponse``."""

    status_code: int = 200
    status: str = "success"
    message: str
    data: UserProfileResponse


class AvatarUploadResponse(BaseModel):
    """Envelope returned after a successful avatar upload."""

    status_code: int = 200
    status: str = "success"
    message: str
    data: UserProfileResponse


class DeleteResponse(BaseModel):
    """Envelope returned after account deletion."""

    status: str = "ok"
    message: str
