"""Authentication Pydantic schemas module.

Strictly defines JSON constraints validating and mutating incoming API properties
automatically.
"""

import uuid
from datetime import datetime

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from app.modules.auth.constants import SupportedLanguage


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
    """Public payload returned by the user update endpoint."""

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
    """Public payload returned by the user endpoint."""

    id: uuid.UUID
    user_role: str
    is_active: bool
    is_verified: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    """Public payload returned by the token endpoint."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenData(BaseModel):
    """Validated, non-optional claims extracted from a token JWT."""

    email: str | None = None
    jti: str | None = None


class RefreshTokenClaims(BaseModel):
    """Validated, non-optional claims extracted from a refresh token JWT."""

    email: str
    jti: str


class SignupRequest(UserBase):
    password: str = Field(..., min_length=8)
    confirm_password: str
    accepted_terms: bool

    @field_validator("accepted_terms", mode="after")
    @classmethod
    def terms_must_be_accepted(cls, value: bool) -> bool:
        if not value:
            raise ValueError(
                "You must accept the Terms of Service and Privacy Policy "
                "to create an account."
            )
        return value

    @model_validator(mode="after")
    def check_passwords_match(self) -> "SignupRequest":
        if self.password != self.confirm_password:
            raise ValueError("passwords do not match")
        return self


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
    status: str = "ok"
    message: str


class ResetPasswordRequest(BaseModel):
    """Payload submitted to ``POST /auth/reset-password``."""

    token: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)


class ChangePasswordRequest(BaseModel):
    """Payload submitted to ``POST /auth/change-password``."""

    current_password: str
    new_password: str = Field(..., min_length=8)


class RefreshTokenResponse(BaseModel):
    """Payload returned on successful token rotation.

    The new refresh token is delivered exclusively via an HttpOnly
    cookie - it is intentionally *not* included in the response body.
    """

    access_token: str
    token_type: str = "bearer"
    expires_in: int
