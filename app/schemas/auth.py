import uuid

from pydantic import BaseModel, EmailStr

from app.schemas.user import UserResponse


class SignupResponse(UserResponse):
    """Public payload returned by the signup endpoint."""


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ActionAcknowledgement(BaseModel):
    message: str


class VerifyEmailResponse(BaseModel):
    status: str = "ok"
    message: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr


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
