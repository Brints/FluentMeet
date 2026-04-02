"""Pydantic schemas for Cloudinary storage operations."""

from pydantic import BaseModel


class UploadResult(BaseModel):
    """Structured response from a successful Cloudinary upload."""

    public_id: str
    secure_url: str
    resource_type: str
    format: str | None = None
    bytes: int = 0
    width: int | None = None
    height: int | None = None


class DeleteResult(BaseModel):
    """Structured response from a Cloudinary delete operation."""

    public_id: str
    result: str  # "ok" | "not found"
