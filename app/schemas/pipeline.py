"""Pydantic event schemas for the real-time audio processing pipeline.

Each schema represents one stage of the pipeline:
    audio.raw → text.original → text.translated → audio.synthesized

All audio payloads use base64 encoding for compatibility with
the existing JSON-based Kafka serializer.
"""

from enum import Enum

from pydantic import BaseModel, Field

from app.kafka.schemas import BaseEvent

# ── Audio Encoding Enum ──────────────────────────────────────────────


class AudioEncoding(str, Enum):  # noqa: UP042
    """Supported audio encoding formats throughout the pipeline."""

    LINEAR16 = "linear16"  # PCM 16-bit signed, little-endian
    OPUS = "opus"


# ── Stage 1: Raw Audio Ingest ────────────────────────────────────────


class AudioChunkPayload(BaseModel):
    """Payload for a single audio chunk from a WebSocket client."""

    room_id: str = Field(..., description="Room the audio originates from.")
    user_id: str = Field(
        ..., description="Speaker's tracking ID (user UUID or guest session UUID)."
    )
    sequence_number: int = Field(
        ..., ge=0, description="Monotonically increasing chunk index."
    )
    audio_data: str = Field(..., description="Base64-encoded raw audio bytes.")
    sample_rate: int = Field(default=16000, description="Audio sample rate in Hz.")
    encoding: AudioEncoding = Field(
        default=AudioEncoding.LINEAR16, description="Audio encoding format."
    )
    source_language: str = Field(
        default="en", description="Speaker's language (ISO 639-1)."
    )


class AudioChunkEvent(BaseEvent[AudioChunkPayload]):
    """Kafka event wrapping a raw audio chunk for the STT stage."""

    event_type: str = "audio.chunk"


# ── Stage 2: Transcribed Text ────────────────────────────────────────


class TranscriptionPayload(BaseModel):
    """Payload produced by the STT worker."""

    room_id: str
    user_id: str
    sequence_number: int = Field(..., ge=0)
    text: str = Field(..., description="Transcribed text from the audio chunk.")
    source_language: str = Field(
        ..., description="Detected or declared source language."
    )
    is_final: bool = Field(
        default=True, description="Whether this is a final transcription or interim."
    )
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="STT confidence score."
    )


class TranscriptionEvent(BaseEvent[TranscriptionPayload]):
    """Kafka event wrapping a transcription result for the Translation stage."""

    event_type: str = "text.transcription"


# ── Stage 3: Translated Text ────────────────────────────────────────


class TranslationPayload(BaseModel):
    """Payload produced by the Translation worker."""

    room_id: str
    user_id: str
    sequence_number: int = Field(..., ge=0)
    original_text: str
    translated_text: str
    source_language: str
    target_language: str


class TranslationEvent(BaseEvent[TranslationPayload]):
    """Kafka event wrapping a translation result for the TTS stage."""

    event_type: str = "text.translation"


# ── Stage 4: Synthesized Audio ───────────────────────────────────────


class SynthesizedAudioPayload(BaseModel):
    """Payload produced by the TTS worker."""

    room_id: str
    user_id: str
    sequence_number: int = Field(..., ge=0)
    audio_data: str = Field(..., description="Base64-encoded synthesized audio bytes.")
    target_language: str
    sample_rate: int = Field(default=16000)
    encoding: AudioEncoding = Field(default=AudioEncoding.LINEAR16)


class SynthesizedAudioEvent(BaseEvent[SynthesizedAudioPayload]):
    """Kafka event wrapping synthesized audio for egress to WebSocket clients."""

    event_type: str = "audio.synthesized"
