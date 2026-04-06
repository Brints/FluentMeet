"""OpenAI TTS provider configuration."""

from app.core.config import settings


def get_openai_tts_headers() -> dict[str, str]:
    """Return authorization headers for the OpenAI TTS API."""
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    return {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
