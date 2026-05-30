"""Deepgram TTS configuration helpers.

Provides header generation and language-to-voice mapping for the
Deepgram Aura-2 TTS API.
"""

from app.core.config import settings

# Deepgram Aura-2 voice models per language.
# Format: "aura-2-{voice}-{lang}" — each language has a default voice.
# See: https://developers.deepgram.com/docs/tts-models
_VOICE_MAP: dict[str, str] = {
    "en": "thalia-en",
    "de": "thalia-de",
    "fr": "thalia-fr",
    "es": "thalia-es",
    "it": "thalia-it",
    "nl": "thalia-nl",
    "ja": "thalia-ja",
}

# Fallback voice when the requested language isn't directly supported
_DEFAULT_VOICE = "thalia-en"


def get_deepgram_tts_headers() -> dict[str, str]:
    """Build HTTP headers for Deepgram TTS API requests.

    Uses the same ``DEEPGRAM_API_KEY`` already configured for STT.

    Returns:
        dict[str, str]: Authorization and content-type headers.
    """
    return {
        "Authorization": f"Token {settings.DEEPGRAM_API_KEY}",
        "Content-Type": "application/json",
    }


def get_voice_model(language: str) -> str:
    """Resolve a language code to a Deepgram Aura-2 voice model name.

    Args:
        language: ISO 639-1 language code (e.g. 'en', 'de').

    Returns:
        str: The voice model identifier for the ``model`` query parameter.
    """
    voice = _VOICE_MAP.get(language.lower(), _DEFAULT_VOICE)
    base_model = settings.DEEPGRAM_TTS_MODEL  # e.g. "aura-2-thalia"
    # Extract the model family prefix (e.g. "aura-2")
    # and combine with the language-specific voice
    model_prefix = base_model.rsplit("-", 1)[0] if "-" in base_model else base_model
    return f"{model_prefix}-{voice}"
