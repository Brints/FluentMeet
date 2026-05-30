"""ElevenLabs Speech-to-Text service module.

Wraps the ElevenLabs Scribe STT API for transcription of pre-recorded
audio chunks.
"""

import logging
import time

import httpx

from app.core.circuit_breaker import AsyncCircuitBreaker
from app.core.config import settings
from app.external_services.elevenlabs_stt.config import (
    get_elevenlabs_stt_headers,
    get_stt_language_code,
)

logger = logging.getLogger(__name__)


class ElevenLabsSTTService:
    """Stateless service for converting audio bytes to text via ElevenLabs Scribe API.

    Provides a centralized client to execute audio transcription calls against
    the ElevenLabs speech-to-text endpoint.
    """

    def __init__(self, timeout: float = 30.0) -> None:
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._breaker = AsyncCircuitBreaker()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        language: str = "en",
        sample_rate: int = 24000,
        encoding: str = "linear16",
    ) -> dict:
        """Send raw audio to ElevenLabs Speech-to-Text and return transcription results.

        Args:
            audio_bytes: Raw audio data.
            language: ISO 639-1 language hint for the STT model.
            sample_rate: Audio sample rate in Hz.
            encoding: Audio encoding format.

        Returns:
            A dict with keys ``text``, ``confidence``,
            ``detected_language``, and ``latency_ms``.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses from ElevenLabs.
        """
        headers = get_elevenlabs_stt_headers()
        model_id = settings.ELEVENLABS_STT_MODEL or "scribe_v2"
        lang_code = get_stt_language_code(language)

        # We must package raw PCM bytes in a WAV container or send with correct mimetype
        # ElevenLabs speech-to-text accepts multiple audio formats. For raw PCM,
        # uploading with an arbitrary filename like 'audio.raw' with content_type
        # 'audio/wav'
        # or 'audio/raw' or wrapping it in a simple WAV header is best.
        # But wait! If it is raw pcm 24kHz linear16, we can write a simple WAV header
        # or we can send it as audio/wav. Let's wrap it in a basic WAV header so the API
        # knows sample rate and channel count, preventing transcription errors.

        wav_data = audio_bytes
        if encoding.lower() in ("linear16", "raw", "pcm"):
            # Construct a basic WAV header
            # 44 bytes header for PCM
            num_channels = 1
            bytes_per_sample = 2  # 16-bit
            byte_rate = sample_rate * num_channels * bytes_per_sample
            block_align = num_channels * bytes_per_sample
            data_size = len(audio_bytes)
            file_size = 36 + data_size

            header = bytearray(44)
            header[0:4] = b"RIFF"
            header[4:8] = file_size.to_bytes(4, "little")
            header[8:12] = b"WAVE"
            header[12:16] = b"fmt "
            header[16:20] = (16).to_bytes(4, "little")  # Subchunk1Size (16 for PCM)
            header[20:22] = (1).to_bytes(2, "little")  # AudioFormat (1 for PCM)
            header[22:24] = num_channels.to_bytes(2, "little")
            header[24:28] = sample_rate.to_bytes(4, "little")
            header[28:32] = byte_rate.to_bytes(4, "little")
            header[32:34] = block_align.to_bytes(2, "little")
            header[34:36] = (bytes_per_sample * 8).to_bytes(
                2, "little"
            )  # BitsPerSample
            header[36:40] = b"data"
            header[40:44] = data_size.to_bytes(4, "little")

            wav_data = bytes(header) + audio_bytes

        # Form data for ElevenLabs
        files = {"file": ("audio.wav", wav_data, "audio/wav")}
        data = {
            "model_id": model_id,
        }
        if lang_code:
            data["language_code"] = lang_code

        async def _call() -> httpx.Response:
            resp = await self.client.post(
                settings.ELEVENLABS_STT_API_URL,
                headers=headers,
                files=files,
                data=data,
            )
            resp.raise_for_status()
            return resp

        start = time.monotonic()
        response = await self._breaker.call(_call)
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.debug("ElevenLabs STT API completed in %.1fms", elapsed_ms)

        resp_json = response.json()

        # ElevenLabs response structure is expected to have 'text', and optionally
        # 'language_code' / 'detected_language'
        text = resp_json.get("text", "")
        detected_language = resp_json.get("language_code", language)

        # Scribe API might return a list of words, let's look for average confidence if
        # available, else default to 1.0
        words = resp_json.get("words", [])
        confidence = 1.0
        if words:
            confidences = [w.get("confidence", 1.0) for w in words if "confidence" in w]
            if confidences:
                confidence = sum(confidences) / len(confidences)

        return {
            "text": text,
            "confidence": confidence,
            "detected_language": detected_language,
            "latency_ms": round(elapsed_ms, 1),
        }


# ── Module-level singleton ────────────────────────────────────────────
_stt_service: ElevenLabsSTTService | None = None


def get_elevenlabs_stt_service() -> ElevenLabsSTTService:
    """Retrieve the singleton instance of the ElevenLabsSTTService.

    Returns:
        ElevenLabsSTTService: The service instance.
    """
    global _stt_service  # noqa: PLW0603
    if _stt_service is None:
        _stt_service = ElevenLabsSTTService()
    return _stt_service
