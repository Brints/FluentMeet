"""OpenAI TTS provider configuration module.

Handles the secure retrieval of authentication headers required for the
OpenAI Text-to-Speech API.
"""

from app.core.config import settings


def get_openai_tts_headers() -> dict[str, str]:
    """Return authorization headers for the OpenAI TTS API.

    Returns:
        dict[str, str]: A dictionary containing the standard Authorization
        and Content-Type parameters mapping to the environment API key.

    Raises:
        RuntimeError: If OPENAI_API_KEY is not configured in the environment.
    """
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    return {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
