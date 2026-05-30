"""ElevenLabs TTS service package."""

from app.external_services.elevenlabs_tts.service import (
    ElevenLabsTTSService,
    get_elevenlabs_tts_service,
)

__all__ = ["ElevenLabsTTSService", "get_elevenlabs_tts_service"]
