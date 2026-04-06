"""Deepgram Speech-to-Text service.

Wraps the Deepgram REST API (/v1/listen) for pre-recorded audio
transcription. Each call sends a single audio chunk and returns
the transcribed text with confidence and detected language.
"""

import logging
import time

import httpx

from app.core.config import settings
from app.external_services.deepgram.config import get_deepgram_headers

logger = logging.getLogger(__name__)


class DeepgramSTTService:
    """Stateless service for converting audio bytes to text via Deepgram."""

    def __init__(self, timeout: float = 10.0) -> None:
        self._timeout = timeout

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        language: str = "en",
        sample_rate: int = 16000,
        encoding: str = "linear16",
    ) -> dict:
        """Send raw audio to Deepgram and return transcription results.

        Args:
            audio_bytes: Raw audio data (PCM or Opus).
            language: ISO 639-1 language hint for the STT model.
            sample_rate: Audio sample rate in Hz.
            encoding: Audio encoding format (``linear16`` or ``opus``).

        Returns:
            A dict with keys ``text``, ``confidence``, ``detected_language``.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses from Deepgram.
        """
        headers = get_deepgram_headers()
        params = {
            "model": settings.DEEPGRAM_MODEL,
            "language": language,
            "encoding": encoding,
            "sample_rate": str(sample_rate),
            "punctuate": "true",
            "smart_format": "true",
        }

        start = time.monotonic()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                settings.DEEPGRAM_API_URL,
                headers=headers,
                params=params,
                content=audio_bytes,
            )
            response.raise_for_status()

        elapsed_ms = (time.monotonic() - start) * 1000
        logger.debug("Deepgram STT completed in %.1fms", elapsed_ms)

        data = response.json()
        # Deepgram response structure:
        # results.channels[0].alternatives[0].transcript
        channel = data.get("results", {}).get("channels", [{}])[0]
        alternative = channel.get("alternatives", [{}])[0]

        return {
            "text": alternative.get("transcript", ""),
            "confidence": alternative.get("confidence", 0.0),
            "detected_language": data.get("results", {}).get("detected_language", language),
            "latency_ms": round(elapsed_ms, 1),
        }


# ── Module-level singleton ────────────────────────────────────────────
_stt_service: DeepgramSTTService | None = None


def get_deepgram_stt_service() -> DeepgramSTTService:
    global _stt_service  # noqa: PLW0603
    if _stt_service is None:
        _stt_service = DeepgramSTTService()
    return _stt_service
