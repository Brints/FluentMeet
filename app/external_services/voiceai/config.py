"""Voice.ai TTS provider configuration module.

Handles the secure retrieval of authentication headers required for the
Voice.ai Text-to-Speech API.
"""

from app.core.config import settings


def get_voiceai_headers() -> dict[str, str]:
    """Return authorization headers for the Voice.ai TTS API.

    Returns:
        dict[str, str]: A dictionary containing the standard Authorization
        and Content-Type parameters mapping to the environment API key.

    Raises:
        RuntimeError: If VOICE_AI_API_KEY is not configured in the environment.
    """
    if not settings.VOICE_AI_API_KEY:
        raise RuntimeError("VOICE_AI_API_KEY is not configured.")
    return {
        "Authorization": f"Bearer {settings.VOICE_AI_API_KEY}",
        "Content-Type": "application/json",
    }
