import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class SupportedLanguage(StrEnum):
    ENGLISH = "en"
    FRENCH = "fr"
    GERMAN = "de"
    SPANISH = "es"
    ITALIAN = "it"
    PORTUGUESE = "pt"


class UserBase(BaseModel):
    email: EmailStr
    full_name: str | None = Field(default=None, max_length=255)
    speaking_language: SupportedLanguage = SupportedLanguage.ENGLISH
    listening_language: SupportedLanguage = SupportedLanguage.ENGLISH

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("full_name", mode="before")
    @classmethod
    def strip_full_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped_value = value.strip()
        return stripped_value or None


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    speaking_language: SupportedLanguage | None = None
    listening_language: SupportedLanguage | None = None
    password: str | None = Field(None, min_length=8)

    @field_validator("full_name", mode="before")
    @classmethod
    def strip_full_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped_value = value.strip()
        return stripped_value or None


class UserResponse(UserBase):
    id: uuid.UUID
    is_active: bool
    is_verified: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenData(BaseModel):
    email: str | None = None
    jti: str | None = None


class RefreshTokenClaims(BaseModel):
    """Validated, non-optional claims extracted from a refresh token JWT."""

    email: str
    jti: str


class SignupRequest(UserBase):
    password: str = Field(..., min_length=8)


class SignupResponse(UserResponse):
    """Public payload returned by the signup endpoint."""


class LoginRequest(BaseModel):
    """Credentials submitted to ``POST /auth/login``."""

    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    """Payload returned on successful login.

    The refresh token is delivered exclusively via an HttpOnly cookie -
    it is intentionally *not* included in the response body.
    """

    access_token: str
    user_id: uuid.UUID
    token_type: str = "bearer"
    expires_in: int


class VerifyEmailResponse(BaseModel):
    status: str = "ok"
    message: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ActionAcknowledgement(BaseModel):
    message: str


class RefreshTokenResponse(BaseModel):
    """Payload returned on successful token rotation.

    The new refresh token is delivered exclusively via an HttpOnly
    cookie - it is intentionally *not* included in the response body.
    """

    access_token: str
    token_type: str = "bearer"
    expires_in: int
