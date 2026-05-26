"""STT (Speech-to-Text) Kafka consumer worker.

Consumes raw audio chunks from ``audio.raw``, calls the Deepgram STT API,
and publishes transcription results to ``text.original``.
"""

import asyncio
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
        # Store streaming connections per user in room
        self._streaming_connections: dict[str, Any] = {}
        self._sequence_counters: dict[str, int] = {}

        from app.modules.meeting.state import MeetingStateService

        self._state = MeetingStateService()

    # Skip audio chunks older than 2 minutes — they belong to sessions whose
    # room IDs no longer exist in Redis, so the translation worker would find
    # no participants and produce nothing anyway.
    max_message_age_ms = 120_000  # 2 minutes

    async def handle(self, event: BaseEvent[Any]) -> None:
        """Process a single audio chunk with buffering or streaming.

        Collect → decode → STT → publish.

        Args:
            event (BaseEvent[Any]): The deserialized wrapper containing the
                AudioChunkPayload.
        """
        chunk_event = AudioChunkEvent.model_validate(event.model_dump())
        payload = chunk_event.payload

        # Decode audio bytes
        audio_bytes = base64.b64decode(payload.audio_data)
        if not audio_bytes:
            return

        buffer_key = f"{payload.room_id}:{payload.user_id}"
        self._buffer_timestamps[buffer_key] = time.monotonic()

        # Periodically sweep stale buffers and connections
        self._sweep_stale_buffers()

        from app.core.config import settings

        use_streaming = settings.DEEPGRAM_USE_STREAMING and settings.DEEPGRAM_API_KEY

        if use_streaming:
            await self._handle_streaming(payload, buffer_key, audio_bytes)
        else:
            await self._handle_batch(payload, buffer_key, audio_bytes)

    async def _handle_streaming(
        self, payload: Any, buffer_key: str, audio_bytes: bytes
    ) -> None:
        """Stream raw audio chunks to Deepgram WebSocket."""
        from app.core.config import settings

        conn = self._streaming_connections.get(buffer_key)
        try:
            if not conn:

                async def on_transcript(
                    transcript_text: str, is_final: bool, confidence: float
                ) -> None:
                    await self._on_streaming_transcript(
                        payload, buffer_key, transcript_text, is_final, confidence
                    )

                from app.external_services.deepgram.streaming import (
                    DeepgramStreamingSTT,
                )

                if not settings.DEEPGRAM_API_KEY:
                    raise ValueError("DEEPGRAM_API_KEY must be set for streaming STT")

                conn = DeepgramStreamingSTT(
                    api_key=settings.DEEPGRAM_API_KEY,
                    room_id=payload.room_id,
                    user_id=payload.user_id,
                    on_transcript=on_transcript,
                    language=payload.source_language,
                    model=settings.DEEPGRAM_MODEL,
                    sample_rate=payload.sample_rate,
                )
                self._streaming_connections[buffer_key] = conn
                await conn.connect()

            await conn.send_audio(audio_bytes)
        except Exception as e:
            logger.error(
                "Error in Deepgram streaming connection for %s: %s",
                buffer_key,
                e,
            )
            if conn:
                task = asyncio.create_task(conn.close())
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
            self._streaming_connections.pop(buffer_key, None)

    async def _on_streaming_transcript(
        self,
        payload: Any,
        buffer_key: str,
        transcript_text: str,
        is_final: bool,
        confidence: float,
    ) -> None:
        """Process incoming transcripts from the streaming connection."""
        text = transcript_text.strip()
        if not text:
            return

        seq_num = self._sequence_counters.get(buffer_key, 0) + 1
        if is_final:
            self._sequence_counters[buffer_key] = seq_num

            transcription_payload = TranscriptionPayload(
                room_id=payload.room_id,
                user_id=payload.user_id,
                sequence_number=seq_num,
                text=text,
                source_language=payload.source_language,
                is_final=True,
                confidence=confidence,
            )
            transcription_event = TranscriptionEvent(payload=transcription_payload)
            await self._producer.send(
                TEXT_ORIGINAL,
                transcription_event,
                key=payload.room_id,
            )

            try:
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

            logger.info(
                "STT (Stream Final): seq=%d room=%s user=%s text='%s' conf=%.2f",
                seq_num,
                payload.room_id,
                payload.user_id,
                text,
                confidence,
            )

        try:
            import json as _json

            from app.modules.auth.token_store import _get_redis_client

            participants = await self._state.get_participants(payload.room_id)
            speaker_name = participants.get(payload.user_id, {}).get(
                "display_name", "Speaker"
            )

            redis = _get_redis_client()
            caption_msg = {
                "event": "caption",
                "type": "original",
                "speaker_id": payload.user_id,
                "speaker_name": speaker_name,
                "text": text,
                "source_language": payload.source_language,
                "is_final": is_final,
                "sequence_number": seq_num,
                "timestamp_ms": int(time.time() * 1000),
            }
            await redis.publish(
                f"pipeline:captions:{payload.room_id}",
                _json.dumps(caption_msg),
            )
        except Exception as redis_err:
            logger.warning("Redis caption publish failed: %s", redis_err)

    async def _handle_batch(
        self, payload: Any, buffer_key: str, audio_bytes: bytes
    ) -> None:
        """Buffer raw audio chunks and call Deepgram batch transcription."""
        from app.core.config import settings

        pipeline_start = time.monotonic()

        if buffer_key not in self._audio_buffers:
            self._audio_buffers[buffer_key] = []

        self._audio_buffers[buffer_key].append(audio_bytes)

        if len(self._audio_buffers[buffer_key]) < self.BUFFER_SIZE:
            return

        full_audio = b"".join(self._audio_buffers[buffer_key])
        self._audio_buffers[buffer_key] = []

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
            return

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

        try:
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

        try:
            import json as _json

            from app.modules.auth.token_store import _get_redis_client

            participants = await self._state.get_participants(payload.room_id)
            speaker_name = participants.get(payload.user_id, {}).get(
                "display_name", "Speaker"
            )

            redis = _get_redis_client()
            caption_msg = {
                "event": "caption",
                "type": "original",
                "speaker_id": payload.user_id,
                "speaker_name": speaker_name,
                "text": text,
                "source_language": transcription_payload.source_language,
                "is_final": True,
                "sequence_number": payload.sequence_number,
                "timestamp_ms": int(time.time() * 1000),
            }
            await redis.publish(
                f"pipeline:captions:{payload.room_id}",
                _json.dumps(caption_msg),
            )
        except Exception as redis_err:
            logger.warning("Redis caption publish failed: %s", redis_err)

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
        """Remove audio buffers/connections idle for 60 seconds."""
        now = time.monotonic()
        stale_keys = [
            key for key, ts in self._buffer_timestamps.items() if now - ts > 60.0
        ]
        for key in stale_keys:
            self._audio_buffers.pop(key, None)
            self._buffer_timestamps.pop(key, None)
            self._sequence_counters.pop(key, None)

            # Close and clean up streaming connection
            conn = self._streaming_connections.pop(key, None)
            if conn:
                task = asyncio.create_task(conn.close())
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)

        if stale_keys:
            logger.debug(
                "Swept %d stale audio buffer(s) and connection(s)", len(stale_keys)
            )
