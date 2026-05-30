"""ElevenLabs TTS (eleven_flash_v2_5) Text-to-Speech service module.

Wraps the ElevenLabs TTS API to convert translated text into synthesized audio.
Supports multilingual voices and raw PCM output.
"""

import logging
import time
from collections.abc import AsyncGenerator

import httpx

from app.core.circuit_breaker import AsyncCircuitBreaker
from app.core.config import settings
from app.external_services.elevenlabs_tts.config import (
    get_elevenlabs_tts_headers,
    get_language_code,
)

logger = logging.getLogger(__name__)


class ElevenLabsTTSService:
    """Stateless service for converting text to speech via ElevenLabs.

    Provides both batch and streaming synthesis methods. Uses the configured
    ``ELEVEN_LABS_API_KEY`` from Settings.
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
        encoding: str = "linear16",  # default is linear16/pcm
    ) -> dict:
        """Convert text to audio bytes via ElevenLabs TTS.

        Args:
            text: The text to synthesize.
            language: ISO 639-1 language code for voice configuration.
                Defaults to ``"en"``.
            encoding: Output encoding. Defaults to ``"linear16"``.

        Returns:
            dict: A dictionary containing ``audio_bytes``, ``sample_rate``,
            and ``latency_ms``.
        """
        headers = get_elevenlabs_tts_headers()
        voice_id = settings.ELEVENLABS_TTS_VOICE_ID or "JBFqnCBsd6RMkjVDRZzb"
        model_id = settings.ELEVENLABS_TTS_MODEL or "eleven_flash_v2_5"
        lang_code = get_language_code(language)

        logger.debug("Synthesizing text with encoding %s", encoding)

        # ElevenLabs accepts pcm_24000 for 24kHz raw PCM
        # Note: If encoding is not linear16, we could support other formats,
        # but the pipeline expects 24kHz raw PCM for linear16.
        output_format = settings.ELEVENLABS_TTS_OUTPUT_FORMAT or "pcm_24000"

        url = f"{settings.ELEVENLABS_TTS_API_URL.rstrip('/')}/{voice_id}"
        params = {"output_format": output_format}

        payload = {
            "text": text,
            "model_id": model_id,
            "language_code": lang_code,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.0,
                "use_speaker_boost": True,
            },
        }

        async def _call() -> httpx.Response:
            resp = await self.client.post(
                url,
                headers=headers,
                json=payload,
                params=params,
            )
            resp.raise_for_status()
            return resp

        start = time.monotonic()
        response = await self._breaker.call(_call)
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.debug("ElevenLabs TTS API completed in %.1fms", elapsed_ms)

        sample_rate = 24000
        if "24000" in output_format:
            sample_rate = 24000
        elif "16000" in output_format:
            sample_rate = 16000
        elif "44100" in output_format:
            sample_rate = 44100

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
        """Stream TTS audio chunks via ElevenLabs streaming endpoint.

        Args:
            text: The text to synthesize.
            language: ISO 639-1 language code. Defaults to ``"en"``.
            encoding: Output encoding. Defaults to ``"linear16"``.

        Yields:
            dict: A dictionary containing ``audio_bytes`` and ``sample_rate``.
        """
        headers = get_elevenlabs_tts_headers()
        voice_id = settings.ELEVENLABS_TTS_VOICE_ID or "JBFqnCBsd6RMkjVDRZzb"
        model_id = settings.ELEVENLABS_TTS_MODEL or "eleven_flash_v2_5"
        lang_code = get_language_code(language)

        logger.debug("Synthesizing stream with encoding %s", encoding)
        output_format = settings.ELEVENLABS_TTS_OUTPUT_FORMAT or "pcm_24000"

        url = f"{settings.ELEVENLABS_TTS_API_URL.rstrip('/')}/{voice_id}/stream"
        params = {"output_format": output_format}

        payload = {
            "text": text,
            "model_id": model_id,
            "language_code": lang_code,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.0,
                "use_speaker_boost": True,
            },
        }

        sample_rate = 24000
        if "24000" in output_format:
            sample_rate = 24000
        elif "16000" in output_format:
            sample_rate = 16000
        elif "44100" in output_format:
            sample_rate = 44100

        start = time.monotonic()
        async with self.client.stream(
            "POST",
            url,
            headers=headers,
            json=payload,
            params=params,
        ) as response:
            response.raise_for_status()
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.debug("ElevenLabs TTS Stream initiated in %.1fms", elapsed_ms)

            async for chunk in response.aiter_bytes(chunk_size=4096):
                if chunk:
                    yield {
                        "audio_bytes": chunk,
                        "sample_rate": sample_rate,
                    }


# ── Module-level singleton ────────────────────────────────────────────
_tts_service: ElevenLabsTTSService | None = None


def get_elevenlabs_tts_service() -> ElevenLabsTTSService:
    """Retrieve the singleton instance of the ElevenLabsTTSService.

    Returns:
        ElevenLabsTTSService: The service instance.
    """
    global _tts_service  # noqa: PLW0603
    if _tts_service is None:
        _tts_service = ElevenLabsTTSService()
    return _tts_service
