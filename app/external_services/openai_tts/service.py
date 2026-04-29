"""OpenAI Text-to-Speech service module.

Wraps the OpenAI TTS API (/v1/audio/speech) to convert translated text
into synthesized audio bytes. Returns raw audio in the configured format.
"""

import logging
import time

import httpx

from app.core.config import settings
from app.external_services.openai_tts.config import get_openai_tts_headers

logger = logging.getLogger(__name__)

# Map our internal encoding names to OpenAI response_format values
_FORMAT_MAP = {
    "linear16": "pcm",
    "opus": "opus",
}


class OpenAITTSService:
    """Stateless service for converting text to speech via OpenAI.

    Provides an asynchronous native wrapper mapping to the REST API,
    translating localized strings into binary audio representations.

    Attributes:
        _timeout (float): Max timeout for HTTP requests mapping to OpenAI.
    """

    def __init__(self, timeout: float = 15.0) -> None:
        self._timeout = timeout

    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        encoding: str = "linear16",
    ) -> dict:
        """Convert text to audio bytes via OpenAI TTS.

        Args:
            text (str): The text to synthesize.
            voice (str | None): OpenAI voice ID
            (alloy, echo, fable, onyx, nova, shimmer). Defaults to None.
            encoding (str): Output encoding (``linear16`` or ``opus``).
            Defaults to "linear16".

        Returns:
            dict: A dictionary containing ``audio_bytes``, ``sample_rate``,
            and ``latency_ms``.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses from OpenAI.
        """
        headers = get_openai_tts_headers()
        response_format = _FORMAT_MAP.get(encoding, "pcm")

        payload = {
            "model": settings.OPENAI_TTS_MODEL,
            "input": text,
            "voice": voice or settings.OPENAI_TTS_VOICE,
            "response_format": response_format,
        }

        start = time.monotonic()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                settings.OPENAI_TTS_API_URL,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()

        elapsed_ms = (time.monotonic() - start) * 1000
        logger.debug("OpenAI TTS completed in %.1fms", elapsed_ms)

        # OpenAI TTS returns raw audio bytes in the response body
        # PCM format: 24kHz, 16-bit, mono
        sample_rate = 24000 if response_format == "pcm" else 48000

        return {
            "audio_bytes": response.content,
            "sample_rate": sample_rate,
            "latency_ms": round(elapsed_ms, 1),
        }


# ── Module-level singleton ────────────────────────────────────────────
_tts_service: OpenAITTSService | None = None


def get_openai_tts_service() -> OpenAITTSService:
    global _tts_service  # noqa: PLW0603
    if _tts_service is None:
        _tts_service = OpenAITTSService()
    return _tts_service
