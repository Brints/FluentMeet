"""Audio bridge: Ingest (WebSocket → Kafka) and Egress (Kafka → WebSocket).

The ``AudioIngestService`` accepts raw audio bytes from a WebSocket handler,
wraps them in an ``AudioChunkEvent``, and publishes to the ``audio.raw`` topic.

The ``AudioEgressRouter`` is a Kafka consumer that reads from
``audio.synthesized`` and routes the synthesized audio back to the correct
room's WebSocket connections gracefully.
"""

import base64
import logging

from app.core.sanitize import log_sanitizer
from app.kafka.manager import get_kafka_manager
from app.kafka.topics import AUDIO_RAW
from app.schemas.pipeline import (
    AudioChunkEvent,
    AudioChunkPayload,
    AudioEncoding,
)

logger = logging.getLogger(__name__)


class AudioIngestService:
    """Publishes raw audio chunks from WebSocket clients to Kafka.

    Used by the WebSocket handler to feed data into the processing pipeline.
    Each chunk is keyed by ``room_id`` for Kafka partition-level ordering.
    """

    def __init__(self) -> None:
        self._sequence_counters: dict[str, int] = {}

    def _next_sequence(self, user_key: str) -> int:
        """Return a monotonically increasing sequence number per user.

        Args:
            user_key (str): The unique identifier for the user in the room.

        Returns:
            int: The next sequence number.
        """
        current = self._sequence_counters.get(user_key, -1)
        current += 1
        self._sequence_counters[user_key] = current
        return current

    def reset_sequence(self, user_key: str) -> None:
        """Reset the sequence counter when a user disconnects.

        Args:
            user_key (str): The unique identifier for the user to reset.
        """
        self._sequence_counters.pop(user_key, None)

    async def publish_audio_chunk(
        self,
        *,
        room_id: str,
        user_id: str,
        audio_bytes: bytes,
        source_language: str = "en",
        sample_rate: int = 16000,
        encoding: str = "linear16",
    ) -> None:
        """Encode and publish an audio chunk to the ``audio.raw`` topic.

        Args:
            room_id (str): The meeting room code.
            user_id (str): Speaker's tracking ID.
            audio_bytes (bytes): Raw audio data (PCM or Opus).
            source_language (str): Speaker's language code.
            sample_rate (int): Audio sample rate in Hz.
            encoding (str): Audio encoding format.
        """
        user_key = f"{room_id}:{user_id}"
        seq = self._next_sequence(user_key)

        audio_b64 = base64.b64encode(audio_bytes).decode("ascii")

        payload = AudioChunkPayload(
            room_id=room_id,
            user_id=user_id,
            sequence_number=seq,
            audio_data=audio_b64,
            sample_rate=sample_rate,
            encoding=AudioEncoding(encoding),
            source_language=source_language,
        )
        event = AudioChunkEvent(payload=payload)

        kafka = get_kafka_manager()
        await kafka.producer.send(AUDIO_RAW, event, key=room_id)

        logger.debug(
            "Published audio chunk seq=%d for user=%s in room=%s",
            seq,
            log_sanitizer.sanitize(user_id),
            log_sanitizer.sanitize(room_id),
        )


# ── Module-level singleton ────────────────────────────────────────────
_ingest_service: AudioIngestService | None = None


def get_audio_ingest_service() -> AudioIngestService:
    """Retrieve the singleton instance of the AudioIngestService.

    Returns:
        AudioIngestService: The service instance.
    """
    global _ingest_service  # noqa: PLW0603
    if _ingest_service is None:
        _ingest_service = AudioIngestService()
    return _ingest_service
