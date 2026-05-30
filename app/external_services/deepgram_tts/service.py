"""Deepgram TTS (Aura-2) Text-to-Speech service module.

Wraps the Deepgram Aura-2 TTS API (POST /v1/speak) to convert translated
text into synthesized audio. Supports multilingual voices and PCM output.

API Reference: https://developers.deepgram.com/docs/text-to-speech
"""

import logging
import time
from collections.abc import AsyncGenerator

import httpx

from app.core.circuit_breaker import AsyncCircuitBreaker
from app.core.config import settings
from app.external_services.deepgram_tts.config import (
    get_deepgram_tts_headers,
    get_voice_model,
)

logger = logging.getLogger(__name__)


class DeepgramTTSService:
    """Stateless service for converting text to speech via Deepgram Aura-2.

    Provides both batch and streaming synthesis methods.  Uses the same
    ``DEEPGRAM_API_KEY`` already configured for STT, so no additional
    credentials are required.

    Attributes:
        _timeout (float): Max timeout for HTTP requests to Deepgram.
    """

    def __init__(self, timeout: float = 60.0) -> None:
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._breaker = AsyncCircuitBreaker()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def synthesize(
        self,
        text: str,
        *,
        language: str = "en",
        encoding: str = "linear16",
    ) -> dict:
        """Convert text to audio bytes via Deepgram Aura-2 TTS.

        Args:
            text: The text to synthesize.
            language: ISO 639-1 language code for voice selection.
                Defaults to ``"en"``.
            encoding: Output encoding (``linear16`` or ``opus``).
                Defaults to ``"linear16"``.

        Returns:
            dict: A dictionary containing ``audio_bytes``, ``sample_rate``,
            and ``latency_ms``.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses from Deepgram.
        """
        headers = get_deepgram_tts_headers()
        model = get_voice_model(language)
        sample_rate = settings.PIPELINE_AUDIO_SAMPLE_RATE  # 24000

        # Build query params for the speak endpoint
        params: dict[str, str] = {
            "model": model,
            "encoding": encoding,
            "sample_rate": str(sample_rate),
        }

        payload = {"text": text}

        async def _call() -> httpx.Response:
            resp = await self.client.post(
                settings.DEEPGRAM_TTS_API_URL,
                headers=headers,
                json=payload,
                params=params,
            )
            resp.raise_for_status()
            return resp

        start = time.monotonic()
        response = await self._breaker.call(_call)

        elapsed_ms = (time.monotonic() - start) * 1000
        logger.debug("Deepgram TTS API completed in %.1fms", elapsed_ms)

        return {
            "audio_bytes": response.content,
            "sample_rate": sample_rate,
            "latency_ms": round(elapsed_ms, 1),
        }

    async def synthesize_stream(
        self,
        text: str,
        *,
        language: str = "en",
        encoding: str = "linear16",
    ) -> AsyncGenerator[dict, None]:
        """Stream TTS audio chunks via Deepgram streaming endpoint.

        Args:
            text: The text to synthesize.
            language: ISO 639-1 language code. Defaults to ``"en"``.
            encoding: Output encoding (``linear16`` or ``opus``).
                Defaults to ``"linear16"``.

        Yields:
            dict: A dictionary containing ``audio_bytes`` and ``sample_rate``.
        """
        headers = get_deepgram_tts_headers()
        model = get_voice_model(language)
        sample_rate = settings.PIPELINE_AUDIO_SAMPLE_RATE

        params: dict[str, str] = {
            "model": model,
            "encoding": encoding,
            "sample_rate": str(sample_rate),
        }

        payload = {"text": text}

        start = time.monotonic()
        async with self.client.stream(
            "POST",
            settings.DEEPGRAM_TTS_API_URL,
            headers=headers,
            json=payload,
            params=params,
        ) as response:
            response.raise_for_status()
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.debug("Deepgram TTS Stream initiated in %.1fms", elapsed_ms)

            async for chunk in response.aiter_bytes(chunk_size=4096):
                if chunk:
                    yield {
                        "audio_bytes": chunk,
                        "sample_rate": sample_rate,
                    }


# ── Module-level singleton ────────────────────────────────────────────
_tts_service: DeepgramTTSService | None = None


def get_deepgram_tts_service() -> DeepgramTTSService:
    """Retrieve the singleton instance of the DeepgramTTSService.

    Returns:
        DeepgramTTSService: The service instance.
    """
    global _tts_service  # noqa: PLW0603
    if _tts_service is None:
        _tts_service = DeepgramTTSService()
    return _tts_service
