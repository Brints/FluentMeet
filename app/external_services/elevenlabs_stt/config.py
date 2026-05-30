"""ElevenLabs STT configuration helpers.

Provides header generation and utility settings for ElevenLabs Speech-to-Text.
"""

from app.core.config import settings


def get_elevenlabs_stt_headers() -> dict[str, str]:
    """Build HTTP headers for ElevenLabs STT API requests.

    Returns:
        dict[str, str]: Authentication headers.
    """
    if not settings.ELEVEN_LABS_API_KEY:
        raise RuntimeError("ELEVEN_LABS_API_KEY is not configured.")
    return {
        "xi-api-key": settings.ELEVEN_LABS_API_KEY,
    }


def get_stt_language_code(language: str) -> str | None:
    """Standardize language code for ElevenLabs STT.

    ElevenLabs STT supports ISO 639-1 language codes (e.g. "en", "de", "es").
    If language is provided, we extract the base language part (e.g. 'en-US' -> 'en').
    """
    if not language:
        return None
    return language.split("-")[0].lower()
