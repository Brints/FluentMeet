"""DeepL Translation service.

Wraps the DeepL REST API (/v2/translate) for text translation.
Falls back to OpenAI GPT-4o-mini when DeepL is unavailable or
the language pair is not supported.
"""

import logging
import time

import httpx

from app.core.config import settings
from app.external_services.deepl.config import get_deepl_headers

logger = logging.getLogger(__name__)

# DeepL uses uppercase language codes for target (e.g. "EN-US", "DE", "FR")
# We normalize ISO 639-1 lowercase to DeepL format.
_DEEPL_LANG_MAP: dict[str, str] = {
    "en": "EN-US",
    "de": "DE",
    "fr": "FR",
    "es": "ES",
    "it": "IT",
    "pt": "PT-BR",
    "nl": "NL",
    "pl": "PL",
    "ru": "RU",
    "ja": "JA",
    "zh": "ZH-HANS",
    "ko": "KO",
    "sv": "SV",
    "da": "DA",
    "fi": "FI",
    "el": "EL",
    "cs": "CS",
    "ro": "RO",
    "hu": "HU",
    "uk": "UK",
    "id": "ID",
    "tr": "TR",
}


class DeepLTranslationService:
    """Stateless service for translating text via DeepL."""

    def __init__(self, timeout: float = 10.0) -> None:
        self._timeout = timeout

    async def translate(
        self,
        text: str,
        *,
        source_language: str,
        target_language: str,
    ) -> dict:
        """Translate text from source to target language.

        Args:
            text: The text to translate.
            source_language: ISO 639-1 source language code.
            target_language: ISO 639-1 target language code.

        Returns:
            A dict with ``translated_text``, ``detected_source``, ``latency_ms``.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses from DeepL.
        """
        deepl_target = _DEEPL_LANG_MAP.get(target_language, target_language.upper())
        deepl_source = source_language.upper() if source_language else None

        headers = get_deepl_headers()
        payload: dict = {
            "text": [text],
            "target_lang": deepl_target,
        }
        if deepl_source:
            payload["source_lang"] = deepl_source

        start = time.monotonic()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                settings.DEEPL_API_URL,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()

        elapsed_ms = (time.monotonic() - start) * 1000
        logger.debug("DeepL translation completed in %.1fms", elapsed_ms)

        data = response.json()
        translations = data.get("translations", [{}])
        first = translations[0] if translations else {}

        return {
            "translated_text": first.get("text", ""),
            "detected_source": first.get("detected_source_language", source_language),
            "latency_ms": round(elapsed_ms, 1),
        }

    def supports_language(self, language_code: str) -> bool:
        """Check if DeepL supports a given target language."""
        return language_code.lower() in _DEEPL_LANG_MAP


class OpenAITranslationFallback:
    """Fallback translation via OpenAI GPT-4o-mini for unsupported DeepL pairs."""

    def __init__(self, timeout: float = 15.0) -> None:
        self._timeout = timeout

    async def translate(
        self,
        text: str,
        *,
        source_language: str,
        target_language: str,
    ) -> dict:
        """Translate text using OpenAI chat completions as a fallback.

        Args:
            text: The text to translate.
            source_language: ISO 639-1 source language code.
            target_language: ISO 639-1 target language code.

        Returns:
            A dict with ``translated_text``, ``latency_ms``.
        """
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not configured for translation fallback.")

        headers = {
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"You are a professional translator. "
                        f"Translate the following text "
                        f"from {source_language} to {target_language}. "
                        f"Return ONLY the translated text, nothing else."
                    ),
                },
                {"role": "user", "content": text},
            ],
            "temperature": 0.3,
        }

        start = time.monotonic()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()

        elapsed_ms = (time.monotonic() - start) * 1000
        logger.debug("OpenAI translation fallback completed in %.1fms", elapsed_ms)

        data = response.json()
        translated = data["choices"][0]["message"]["content"].strip()

        return {
            "translated_text": translated,
            "latency_ms": round(elapsed_ms, 1),
        }


# ── Module-level singletons ──────────────────────────────────────────
_deepl_service: DeepLTranslationService | None = None
_openai_fallback: OpenAITranslationFallback | None = None


def get_deepl_translation_service() -> DeepLTranslationService:
    global _deepl_service  # noqa: PLW0603
    if _deepl_service is None:
        _deepl_service = DeepLTranslationService()
    return _deepl_service


def get_openai_translation_fallback() -> OpenAITranslationFallback:
    global _openai_fallback  # noqa: PLW0603
    if _openai_fallback is None:
        _openai_fallback = OpenAITranslationFallback()
    return _openai_fallback
