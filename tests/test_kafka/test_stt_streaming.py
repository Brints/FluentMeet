import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.pipeline import AudioChunkEvent, AudioChunkPayload, AudioEncoding


@pytest.fixture
def base_audio_chunk_event():
    payload = AudioChunkPayload(
        room_id="room123",
        user_id="user456",
        sequence_number=1,
        audio_data=base64.b64encode(b"fake_audio").decode("ascii"),
        source_language="en",
        sample_rate=16000,
        encoding=AudioEncoding.LINEAR16,
    )
    return AudioChunkEvent(payload=payload)


@pytest.mark.asyncio
async def test_stt_worker_handle_streaming(base_audio_chunk_event):
    from app.services.stt_worker import STTWorker

    mock_producer = AsyncMock()
    worker = STTWorker(producer=mock_producer)

    with (
        patch("app.core.config.settings") as mock_settings,
        patch("app.services.connection_manager.get_connection_manager") as mock_get_cm,
        patch("app.modules.auth.token_store._get_redis_client") as mock_get_redis,
        patch(
            "app.external_services.deepgram.streaming.DeepgramStreamingSTT"
        ) as mock_streaming_class,
    ):
        mock_settings.DEEPGRAM_API_KEY = "fake-key"
        mock_settings.DEEPGRAM_USE_STREAMING = True
        mock_settings.DEEPGRAM_MODEL = "nova-2"

        # Mock DeepgramStreamingSTT instance
        mock_conn = AsyncMock()
        mock_streaming_class.return_value = mock_conn

        redis_mock = MagicMock()
        redis_mock.publish = AsyncMock()
        mock_get_redis.return_value = redis_mock

        cm_mock = MagicMock()
        cm_mock.broadcast_to_room = AsyncMock()
        mock_get_cm.return_value = cm_mock

        mock_state = AsyncMock()
        mock_state.get_participants.return_value = {
            "user456": {"display_name": "Speaker Name"}
        }
        worker._state = mock_state

        # Call STT worker handle
        await worker.handle(base_audio_chunk_event)

        # Assert DeepgramStreamingSTT was created and connected
        mock_streaming_class.assert_called_once()
        kwargs = mock_streaming_class.call_args[1]
        assert kwargs["api_key"] == "fake-key"
        assert kwargs["room_id"] == "room123"
        assert kwargs["user_id"] == "user456"
        assert kwargs["language"] == "en"
        assert kwargs["model"] == "nova-2"
        assert kwargs["sample_rate"] == 16000

        # Assert send_audio was called with decoded bytes
        mock_conn.connect.assert_called_once()
        mock_conn.send_audio.assert_called_once_with(b"fake_audio")

        # Now simulate transcript callback trigger
        on_transcript_callback = kwargs["on_transcript"]

        # Trigger transcript callback
        await on_transcript_callback("Hello from stream", True, 0.95)

        # Assert TEXT_ORIGINAL event published to producer
        mock_producer.send.assert_called_once()
        args, send_kwargs = mock_producer.send.call_args
        assert args[0] == "text.original"
        assert args[1].payload.text == "Hello from stream"
        assert args[1].payload.sequence_number == 1
        assert send_kwargs["key"] == "room123"

        # Assert active speaker broadcasted
        cm_mock.broadcast_to_room.assert_called_once_with(
            "room123",
            {
                "type": "active_speaker_changed",
                "user_id": "user456",
            },
        )

        # Assert captions published to Redis Pub/Sub
        redis_mock.publish.assert_called_once()
        redis_args = redis_mock.publish.call_args[0]
        assert redis_args[0] == "pipeline:captions:room123"
