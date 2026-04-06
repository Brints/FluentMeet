"""Deepgram provider configuration."""

from app.core.config import settings


def get_deepgram_headers() -> dict[str, str]:
    """Return authorization headers for the Deepgram REST API."""
    if not settings.DEEPGRAM_API_KEY:
        raise RuntimeError("DEEPGRAM_API_KEY is not configured.")
    return {
        "Authorization": f"Token {settings.DEEPGRAM_API_KEY}",
        "Content-Type": "audio/raw",
    }
