"""Cloudinary SDK initialization."""

import cloudinary

from app.core.config import settings


def configure_cloudinary() -> None:
    """Configure the Cloudinary SDK with application credentials.

    Must be called once at startup (or lazily on first use) before any
    upload / delete operation.
    """
    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True,
    )


_configured = False


def ensure_configured() -> None:
    """Idempotent helper — configures Cloudinary at most once."""
    global _configured  # noqa: PLW0603
    if not _configured:
        configure_cloudinary()
        _configured = True
