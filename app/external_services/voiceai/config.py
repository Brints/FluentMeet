"""Voice.ai TTS provider configuration."""

from app.core.config import settings


def get_voiceai_headers() -> dict[str, str]:
    """Return authorization headers for the Voice.ai TTS API."""
    if not settings.VOICE_AI_API_KEY:
        raise RuntimeError("VOICE_AI_API_KEY is not configured.")
    return {
        "Authorization": f"Bearer {settings.VOICE_AI_API_KEY}",
        "Content-Type": "application/json",
    }
