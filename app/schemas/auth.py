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
