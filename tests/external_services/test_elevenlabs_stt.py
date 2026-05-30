from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.config import settings
from app.external_services.elevenlabs_stt.config import get_stt_language_code
from app.external_services.elevenlabs_stt.service import get_elevenlabs_stt_service


def test_elevenlabs_stt_language_mapping():
    assert get_stt_language_code("en-US") == "en"
    assert get_stt_language_code("de-DE") == "de"
    assert get_stt_language_code("fr") == "fr"
    assert get_stt_language_code(None) is None


@pytest.mark.asyncio
async def test_elevenlabs_stt_transcribe():
    # Setup
    settings.ELEVEN_LABS_API_KEY = "test_stt_key"
    settings.ELEVENLABS_STT_MODEL = "scribe_v2"

    response_data = {
        "text": "Hello this is Scribe transcribing.",
        "language_code": "en",
        "words": [
            {"text": "Hello", "start": 0.0, "end": 0.5, "confidence": 0.98},
            {"text": "this", "start": 0.5, "end": 0.8, "confidence": 0.99},
        ],
    }

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json = MagicMock(return_value=response_data)
    mock_response.raise_for_status = MagicMock()

    service = get_elevenlabs_stt_service()

    with patch.object(service.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        # 24000Hz PCM audio chunk:
        # (24000 samples/sec * 2 bytes/sample * 0.1s = 4800 bytes)
        fake_pcm = b"\x00" * 4800

        result = await service.transcribe(
            fake_pcm,
            language="en",
            sample_rate=24000,
            encoding="linear16",
        )

        # Assertions
        mock_post.assert_called_once()
        _args, kwargs = mock_post.call_args
        assert kwargs["headers"]["xi-api-key"] == "test_stt_key"

        assert result["text"] == "Hello this is Scribe transcribing."
        assert result["detected_language"] == "en"
        # confidence is average of words: (0.98 + 0.99) / 2 = 0.985
        assert result["confidence"] == 0.985
        assert "latency_ms" in result
