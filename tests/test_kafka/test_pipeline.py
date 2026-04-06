import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.pipeline import (
    AudioChunkEvent,
    AudioChunkPayload,
    AudioEncoding,
    TranscriptionEvent,
    TranscriptionPayload,
    TranslationEvent,
    TranslationPayload,
)
from app.services.stt_worker import STTWorker
from app.services.translation_worker import TranslationWorker
from app.services.tts_worker import TTSWorker


@pytest.fixture
def mock_producer():
    producer = MagicMock()
    producer.send = AsyncMock()
    return producer


@pytest.fixture
def base_audio_chunk_event() -> AudioChunkEvent:
    payload = AudioChunkPayload(
        room_id="room123",
        user_id="user456",
        sequence_number=1,
        audio_data=base64.b64encode(b"fake_audio").decode("ascii"),
        sample_rate=16000,
        encoding=AudioEncoding.LINEAR16,
        source_language="en",
    )
    return AudioChunkEvent(payload=payload)


@pytest.fixture
def base_transcription_event() -> TranscriptionEvent:
    payload = TranscriptionPayload(
        room_id="room123",
        user_id="user456",
        sequence_number=1,
        text="Hello world",
        source_language="en",
        is_final=True,
        confidence=0.95,
    )
    return TranscriptionEvent(payload=payload)


@pytest.fixture
def base_translation_event() -> TranslationEvent:
    payload = TranslationPayload(
        room_id="room123",
        user_id="user456",
        sequence_number=1,
        original_text="Hello world",
        translated_text="Bonjour le monde",
        source_language="en",
        target_language="fr",
    )
    return TranslationEvent(payload=payload)


@pytest.mark.asyncio
async def test_stt_worker_handle(mock_producer, base_audio_chunk_event):
    worker = STTWorker(producer=mock_producer)

    with patch("app.services.stt_worker.get_deepgram_stt_service") as mock_get_stt:
        mock_stt_svc = AsyncMock()
        mock_stt_svc.transcribe.return_value = {
            "text": "Hello audio",
            "confidence": 0.99,
            "detected_language": "en",
        }
        mock_get_stt.return_value = mock_stt_svc

        await worker.handle(base_audio_chunk_event)

        mock_stt_svc.transcribe.assert_called_once_with(
            b"fake_audio",
            language="en",
            sample_rate=16000,
            encoding="linear16",
        )
        mock_producer.send.assert_called_once()
        args, kwargs = mock_producer.send.call_args
        assert args[0] == "text.original"
        assert isinstance(args[1], TranscriptionEvent)
        assert args[1].payload.text == "Hello audio"
        assert kwargs["key"] == "room123"


@pytest.mark.asyncio
async def test_translation_worker_handle(mock_producer, base_transcription_event):
    worker = TranslationWorker(producer=mock_producer)

    with (
        patch(
            "app.services.translation_worker.MeetingStateService"
        ) as _mock_state_class,
        patch(
            "app.services.translation_worker.get_deepl_translation_service"
        ) as mock_get_deepl,
    ):
        mock_state = AsyncMock()
        # Two users with different languages (fr and es)
        mock_state.get_participants.return_value = {
            "u1": {"language": "fr"},
            "u2": {"language": "es"},
            "u3": {"language": "en"},  # Same as source, should not translate
        }
        worker._state = mock_state

        mock_deepl = AsyncMock()
        mock_deepl.supports_language.return_value = True
        mock_deepl.translate.side_effect = (
            lambda _text, _source_language, target_language: {
                "translated_text": f"Transl => {target_language}",
                "latency_ms": 100,
            }
        )
        mock_get_deepl.return_value = mock_deepl

        await worker.handle(base_transcription_event)

        # Should translate twice (once for FR, once for ES)
        assert mock_deepl.translate.call_count == 2
        assert mock_producer.send.call_count == 2

        # Verify published events
        calls = mock_producer.send.call_args_list
        targets = set()
        for call in calls:
            args, kwargs = call
            assert args[0] == "text.translated"
            assert isinstance(args[1], TranslationEvent)
            targets.add(args[1].payload.target_language)
            assert kwargs["key"] == "room123"

        assert targets == {"fr", "es"}


@pytest.mark.asyncio
async def test_tts_worker_handle(mock_producer, base_translation_event):
    worker = TTSWorker(producer=mock_producer)

    with (
        patch("app.services.tts_worker.get_openai_tts_service") as mock_get_openai,
        patch("app.services.tts_worker.settings") as mock_settings,
    ):
        mock_settings.ACTIVE_TTS_PROVIDER = "openai"
        mock_settings.PIPELINE_AUDIO_ENCODING = "linear16"

        mock_openai = AsyncMock()
        mock_openai.synthesize.return_value = {
            "audio_bytes": b"synthetic_audio_bytes",
            "sample_rate": 24000,
        }
        mock_get_openai.return_value = mock_openai

        await worker.handle(base_translation_event)

        mock_openai.synthesize.assert_called_once_with(
            "Bonjour le monde",
            encoding="linear16",
        )

        mock_producer.send.assert_called_once()
        args, _kwargs = mock_producer.send.call_args
        assert args[0] == "audio.synthesized"

        synth_event = args[1]
        assert synth_event.payload.sample_rate == 24000
        assert synth_event.payload.target_language == "fr"

        decoded = base64.b64decode(synth_event.payload.audio_data)
        assert decoded == b"synthetic_audio_bytes"
