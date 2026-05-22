"""STT (Speech-to-Text) Kafka consumer worker.

Consumes raw audio chunks from ``audio.raw``, calls the Deepgram STT API,
and publishes transcription results to ``text.original``.
"""

import base64
import logging
import time
from typing import Any

from app.external_services.deepgram.service import get_deepgram_stt_service
from app.kafka.consumer import BaseConsumer
from app.kafka.schemas import BaseEvent
from app.kafka.topics import AUDIO_RAW, TEXT_ORIGINAL
from app.schemas.pipeline import (
    AudioChunkEvent,
    TranscriptionEvent,
    TranscriptionPayload,
)

logger = logging.getLogger(__name__)


class STTWorker(BaseConsumer):
    """Kafka consumer that transcribes audio chunks via Deepgram.

    Subscribes to ``audio.raw`` and publishes ``TranscriptionEvent``
    messages to ``text.original``.

    Attributes:
        topic: The Kafka topic for incoming raw audio chunks.
        group_id: Consumer group identifier for STT processing.
        event_schema: Pydantic schema used to validate incoming chunks.
    """

    topic = AUDIO_RAW
    group_id = "stt-worker-group"
    event_schema = AudioChunkEvent

    # Buffer configuration
    BUFFER_SIZE = 5  # Number of 100ms chunks to buffer (500ms total)

    def __init__(self, producer: Any) -> None:
        super().__init__(producer)
        # Store buffers per user in room: { "room:user": [chunk1, chunk2, ...] }
        self._audio_buffers: dict[str, list[bytes]] = {}
        self._buffer_timestamps: dict[str, float] = {}

    # Skip audio chunks older than 2 minutes — they belong to sessions whose
    # room IDs no longer exist in Redis, so the translation worker would find
    # no participants and produce nothing anyway.
    max_message_age_ms = 120_000  # 2 minutes

    async def handle(self, event: BaseEvent[Any]) -> None:
        """Process a single audio chunk with buffering.

        Collect → decode → STT → publish.

        Args:
            event (BaseEvent[Any]): The deserialized wrapper containing the
                AudioChunkPayload.
        """
        chunk_event = AudioChunkEvent.model_validate(event.model_dump())
        payload = chunk_event.payload

        pipeline_start = time.monotonic()

        # 1. Decode and Buffer
        audio_bytes = base64.b64decode(payload.audio_data)
        if not audio_bytes:
            return

        buffer_key = f"{payload.room_id}:{payload.user_id}"
        if buffer_key not in self._audio_buffers:
            self._audio_buffers[buffer_key] = []

        self._audio_buffers[buffer_key].append(audio_bytes)
        self._buffer_timestamps[buffer_key] = time.monotonic()

        # Periodically sweep stale buffers (older than 60 seconds)
        self._sweep_stale_buffers()

        # Only proceed if we have enough chunks to make transcription viable
        if len(self._audio_buffers[buffer_key]) < self.BUFFER_SIZE:
            return

        # Concatenate buffered chunks
        full_audio = b"".join(self._audio_buffers[buffer_key])
        self._audio_buffers[buffer_key] = []  # Clear buffer for next cycle

        # 2. Call Deepgram STT (or Mock it if no API Key provided)
        from app.core.config import settings

        if not settings.DEEPGRAM_API_KEY:
            logger.info("DEEPGRAM_API_KEY not set. Mocking STT response for testing.")
            result: dict[str, Any] = {
                "text": (
                    "Hello, this is a simulated transcription for testing purposes."
                ),
                "detected_language": payload.source_language,
                "confidence": 1.0,
            }
        else:
            stt_service = get_deepgram_stt_service()
            result = await stt_service.transcribe(
                full_audio,
                language=payload.source_language,
                sample_rate=payload.sample_rate,
                encoding=payload.encoding.value,
            )

        text = result.get("text", "").strip()
        if not text:
            # If still no text after 500ms, it's likely just background noise/silence
            return

        # 3. Build and publish transcription event
        transcription_payload = TranscriptionPayload(
            room_id=payload.room_id,
            user_id=payload.user_id,
            sequence_number=payload.sequence_number,
            text=text,
            source_language=result.get("detected_language", payload.source_language),
            is_final=True,
            confidence=result.get("confidence", 0.0),
        )
        transcription_event = TranscriptionEvent(payload=transcription_payload)

        await self._producer.send(
            TEXT_ORIGINAL, transcription_event, key=payload.room_id
        )

        # Broadcast active speaker event over WebSocket
        try:
            import asyncio

            from app.services.connection_manager import get_connection_manager

            manager = get_connection_manager()
            task = asyncio.create_task(
                manager.broadcast_to_room(
                    payload.room_id,
                    {
                        "type": "active_speaker_changed",
                        "user_id": payload.user_id,
                    },
                )
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
        except Exception as e:
            logger.error("Failed to broadcast active speaker: %s", e)

        # Publish transcription caption to Redis Pub/Sub for real-time delivery
        try:
            import json as _json

            from app.modules.auth.token_store import _get_redis_client

            redis = _get_redis_client()
            caption_msg = {
                "event": "caption",
                "speaker_id": payload.user_id,
                "text": text,
                "language": transcription_payload.source_language,
                "is_final": True,
                "is_translation": False,
                "timestamp_ms": int(time.time() * 1000),
            }
            await redis.publish(
                f"pipeline:captions:{payload.room_id}",
                _json.dumps(caption_msg),
            )
        except Exception as redis_err:
            logger.warning("Redis caption publish failed: %s", redis_err)

        # 4. Log pipeline latency
        elapsed_ms = (time.monotonic() - pipeline_start) * 1000
        logger.info(
            "STT: seq=%d room=%s user=%s text='%s' confidence=%.2f latency=%.1fms",
            payload.sequence_number,
            payload.room_id,
            payload.user_id,
            text,
            result.get("confidence", 0.0),
            elapsed_ms,
        )

    def _sweep_stale_buffers(self) -> None:
        """Remove audio buffers that haven't received new chunks in 60 seconds."""
        now = time.monotonic()
        stale_keys = [
            key for key, ts in self._buffer_timestamps.items() if now - ts > 60.0
        ]
        for key in stale_keys:
            self._audio_buffers.pop(key, None)
            self._buffer_timestamps.pop(key, None)
        if stale_keys:
            logger.debug("Swept %d stale audio buffer(s)", len(stale_keys))
