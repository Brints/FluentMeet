"""ElevenLabs Speech-to-Text (scribe_v2 / scribe_v2_realtime) service package."""

from app.external_services.elevenlabs_stt.service import (
    ElevenLabsSTTService,
    get_elevenlabs_stt_service,
)
from app.external_services.elevenlabs_stt.streaming import ElevenLabsStreamingSTT

__all__ = [
    "ElevenLabsSTTService",
    "ElevenLabsStreamingSTT",
    "get_elevenlabs_stt_service",
]
