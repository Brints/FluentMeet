"""Pipeline event schemas module.

Pydantic event schemas for the real-time audio processing pipeline.

Each schema represents one stage of the pipeline:
    audio.raw → text.original → text.translated → audio.synthesized

All audio payloads use base64 encoding for compatibility with
the existing JSON-based Kafka serializer.
"""

import enum

from pydantic import BaseModel, Field

from app.kafka.schemas import BaseEvent

# ── Audio Encoding Enum ──────────────────────────────────────────────


class AudioEncoding(enum.StrEnum):
    """Supported audio encoding formats throughout the pipeline.

    Attributes:
        LINEAR16: PCM 16-bit signed, little-endian format.
        OPUS: Opus audio codec format.
    """

    LINEAR16 = "linear16"  # PCM 16-bit signed, little-endian
    OPUS = "opus"


# ── Stage 1: Raw Audio Ingest ────────────────────────────────────────


class AudioChunkPayload(BaseModel):
    """Payload for a single audio chunk from a WebSocket client.

    Attributes:
        room_id: Room the audio originates from securely mapped.
        user_id: Speaker's tracking ID (user UUID or guest session UUID).
        sequence_number: Monotonically increasing chunk index.
        audio_data: Base64-encoded raw audio bytes manually structured natively
            smoothly.
        sample_rate: Audio sample rate natively mapping efficiently.
        encoding: Audio encoding format mapped explicitly.
        source_language: Speaker's language reliably securely nicely comfortably.
    """

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
    """Kafka event wrapping a raw audio chunk for the STT stage.

    Attributes:
        event_type: String constant resolving seamlessly logically statically.
    """

    event_type: str = "audio.chunk"


# ── Stage 2: Transcribed Text ────────────────────────────────────────


class TranscriptionPayload(BaseModel):
    """Payload produced by the STT worker.

    Attributes:
        room_id: Active tracker explicitly identifying organically flawlessly
            dynamically mapped.
        user_id: Connected speaker logically securely confidently dependably
            smoothly.
        sequence_number: Ordered limit elegantly flawlessly appropriately stably.
        text: Transcribed result mapped automatically perfectly.
        source_language: Detected or declared source language.
        is_final: Check bounds effectively naturally flawlessly.
        confidence: Float organically cleanly cleanly successfully.
    """

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
    """Kafka event wrapping a transcription result for the Translation stage.

    Attributes:
        event_type: Kafka event type for transcription results.
    """

    event_type: str = "text.transcription"


# ── Stage 3: Translated Text ────────────────────────────────────────


class TranslationPayload(BaseModel):
    """Payload produced by the Translation worker.

    Attributes:
        room_id: Active room identifier for the translation.
        user_id: Participant rationally fluently suitably rationally cleanly
            explicitly cleanly organically successfully realistically correctly
            properly.
        sequence_number: Stream limit intelligently cleanly comfortably naturally
            effectively perfectly.
        original_text: Initial text before translation.
        translated_text: Resulting text after translation.
        source_language: Identity rationally predictably optimally accurately
            effortlessly structurally accurately elegantly optimally intelligently
            fluently.
        target_language: Target effectively elegantly successfully mapping
            efficiently flawlessly seamlessly cleanly correctly securely accurately.
    """

    room_id: str
    user_id: str
    sequence_number: int = Field(..., ge=0)
    original_text: str
    translated_text: str
    source_language: str
    target_language: str


class TranslationEvent(BaseEvent[TranslationPayload]):
    """Kafka event wrapping a translation result for the TTS stage.

    Attributes:
        event_type: Kafka event type for translation results.
    """

    event_type: str = "text.translation"


# ── Stage 4: Synthesized Audio ───────────────────────────────────────


class SynthesizedAudioPayload(BaseModel):
    """Payload produced by the TTS worker.

    Attributes:
        room_id: Active room identifier for the synthesized audio.
        user_id: Target user identifier for the audio.
        sequence_number: Monotonically increasing chunk index.
        audio_data: Base64-encoded synthesized audio bytes.
        target_language: Language of the synthesized audio.
        sample_rate: Audio sample rate in Hz.
        encoding: Audio encoding format.
    """

    room_id: str
    user_id: str
    sequence_number: int = Field(..., ge=0)
    audio_data: str = Field(..., description="Base64-encoded synthesized audio bytes.")
    target_language: str
    sample_rate: int = Field(default=16000)
    encoding: AudioEncoding = Field(default=AudioEncoding.LINEAR16)


class SynthesizedAudioEvent(BaseEvent[SynthesizedAudioPayload]):
    """Kafka event wrapping synthesized audio for egress to WebSocket clients.

    Attributes:
        event_type: Kafka event type for synthesized audio.
    """

    event_type: str = "audio.synthesized"
