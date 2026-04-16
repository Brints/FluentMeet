"""Deepgram provider configuration module.

Handles the secure retrieval of authentication headers required for the
Deepgram Speech-to-Text API.
"""

from app.core.config import settings


def get_deepgram_headers() -> dict[str, str]:
    """Return authorization headers for the Deepgram REST API.

    Returns:
        dict[str, str]: A dictionary containing the Authorization and
        Content-Type headers mapping to the environment API key.

    Raises:
        RuntimeError: If DEEPGRAM_API_KEY is not configured in the environment.
    """
    if not settings.DEEPGRAM_API_KEY:
        raise RuntimeError("DEEPGRAM_API_KEY is not configured.")
    return {
        "Authorization": f"Token {settings.DEEPGRAM_API_KEY}",
        "Content-Type": "audio/raw",
    }
