"""Voice.ai Text-to-Speech service module.

Wraps the Voice.ai TTS API (POST /api/v1/tts/speech) to convert translated
text into synthesized audio. Supports multilingual voices, PCM/Opus output,
and voice cloning via voice_id.

API Reference: https://voice.ai/docs/api-reference/text-to-speech/generate-speech
"""

import logging
import time

import httpx

from app.core.config import settings
from app.external_services.voiceai.config import get_voiceai_headers

logger = logging.getLogger(__name__)

# Map our internal encoding names to Voice.ai audio_format values
_FORMAT_MAP = {
    "linear16": "pcm_16000",
    "opus": "opus_48000_64",
}


class VoiceAITTSService:
    """Stateless service for converting text to speech via Voice.ai.

    Provides an asynchronous native wrapper mapping to the REST API,
    translating localized strings into binary audio representations.

    Attributes:
        _timeout (float): Max timeout for HTTP requests mapping to Voice.ai.
    """

    def __init__(self, timeout: float = 60.0) -> None:
        self._timeout = timeout

    async def synthesize(
        self,
        text: str,
        *,
        language: str = "en",
        voice_id: str | None = None,
        encoding: str = "linear16",
    ) -> dict:
        """Convert text to audio bytes via Voice.ai TTS.

        Args:
            text (str): The text to synthesize.
            language (str): ISO 639-1 language code for voice selection. Defaults to "en".
            voice_id (str | None): Optional Voice.ai voice ID. Uses default if omitted.
            encoding (str): Output encoding (``linear16`` or ``opus``). Defaults to "linear16".

        Returns:
            dict: A dictionary containing ``audio_bytes``, ``sample_rate``,
            and ``latency_ms``.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses from Voice.ai.
        """
        headers = get_voiceai_headers()
        audio_format = _FORMAT_MAP.get(encoding, "pcm_16000")

        # Determine sample rate from the format string
        sample_rate = 16000
        if "48000" in audio_format:
            sample_rate = 48000

        # Select model: multilingual for non-English, standard for English
        model = settings.VOICEAI_TTS_MODEL
        if language == "en" and "multilingual" in model:
            model = model.replace("multilingual-", "")

        payload: dict = {
            "text": text,
            "audio_format": audio_format,
            "model": model,
            "language": language,
            "temperature": 1,
            "top_p": 0.8,
        }
        print(f"Voice.ai Audio format: {audio_format}")
        if voice_id:
            payload["voice_id"] = voice_id

        start = time.monotonic()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                settings.VOICEAI_TTS_API_URL,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()

        elapsed_ms = (time.monotonic() - start) * 1000
        print(f"Voice.ai TTS API completed in {elapsed_ms} ms")
        logger.debug("Voice.ai TTS completed in %.1fms", elapsed_ms)

        return {
            "audio_bytes": response.content,
            "sample_rate": sample_rate,
            "latency_ms": round(elapsed_ms, 1),
        }


# ── Module-level singleton ────────────────────────────────────────────
_tts_service: VoiceAITTSService | None = None


def get_voiceai_tts_service() -> VoiceAITTSService:
    global _tts_service  # noqa: PLW0603
    if _tts_service is None:
        _tts_service = VoiceAITTSService()
    return _tts_service
