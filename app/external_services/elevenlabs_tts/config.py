"""ElevenLabs TTS configuration helpers.

Provides header generation and language mapping for the ElevenLabs TTS API.
"""

from app.core.config import settings

# ElevenLabs language mappings for multilingual models
# Maps ISO 639-1 code to ElevenLabs language codes.
_LANGUAGE_MAP: dict[str, str] = {
    "ar": "ar",
    "bg": "bg",
    "zh": "cmn",
    "hr": "hr",
    "cs": "cs",
    "da": "da",
    "nl": "nl",
    "en": "en",
    "fil": "fil",
    "fi": "fi",
    "fr": "fr",
    "de": "de",
    "el": "el",
    "hi": "hi",
    "id": "id",
    "it": "it",
    "ja": "ja",
    "ko": "ko",
    "ms": "ms",
    "pl": "pl",
    "pt": "pt",
    "ro": "ro",
    "ru": "ru",
    "sk": "sk",
    "es": "es",
    "sv": "sv",
    "ta": "ta",
    "tr": "tr",
    "uk": "uk",
}

_DEFAULT_LANGUAGE = "en"


def get_elevenlabs_tts_headers() -> dict[str, str]:
    """Build HTTP headers for ElevenLabs TTS API requests.

    Returns:
        dict[str, str]: Authorization and content-type headers.
    """
    return {
        "xi-api-key": settings.ELEVEN_LABS_API_KEY or "",
        "Content-Type": "application/json",
    }


def get_language_code(language: str) -> str:
    """Resolve an ISO 639-1 language code to ElevenLabs language code.

    Args:
        language: ISO 639-1 language code (e.g. 'en', 'zh').

    Returns:
        str: The ElevenLabs language code.
    """
    if not language:
        return _DEFAULT_LANGUAGE
    # Extract prefix if language has a locale (e.g., 'en-US' -> 'en')
    base_lang = language.split("-")[0].lower()
    return _LANGUAGE_MAP.get(base_lang, _DEFAULT_LANGUAGE)
