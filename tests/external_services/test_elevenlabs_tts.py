from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.config import settings
from app.external_services.elevenlabs_tts.config import get_language_code
from app.external_services.elevenlabs_tts.service import get_elevenlabs_tts_service


def test_elevenlabs_tts_language_mapping():
    assert get_language_code("en") == "en"
    assert get_language_code("en-US") == "en"
    assert get_language_code("zh") == "cmn"
    assert get_language_code("zh-CN") == "cmn"
    assert get_language_code("de") == "de"
    assert get_language_code("unknown") == "en"
    assert get_language_code(None) == "en"


@pytest.mark.asyncio
async def test_elevenlabs_tts_synthesize():
    # Setup
    settings.ELEVEN_LABS_API_KEY = "test_key"
    settings.ELEVENLABS_TTS_VOICE_ID = "voice_abc"
    settings.ELEVENLABS_TTS_MODEL = "eleven_flash_v2_5"

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.content = b"audio_bytes_123"
    mock_response.raise_for_status = MagicMock()

    service = get_elevenlabs_tts_service()

    # We patch the httpx client's post method
    with patch.object(service.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        result = await service.synthesize("Hello world", language="en")

        # Assertions
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert "voice_abc" in args[0]
        assert kwargs["headers"]["xi-api-key"] == "test_key"
        assert kwargs["params"]["output_format"] == "pcm_24000"

        assert result["audio_bytes"] == b"audio_bytes_123"
        assert result["sample_rate"] == 24000
        assert "latency_ms" in result


@pytest.mark.asyncio
async def test_elevenlabs_tts_synthesize_stream():
    # Setup
    settings.ELEVEN_LABS_API_KEY = "test_key"
    settings.ELEVENLABS_TTS_VOICE_ID = "voice_abc"

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    # Mock aiter_bytes async generator
    async def mock_aiter_bytes(chunk_size=None):
        _ = chunk_size
        yield b"stream_chunk_123"

    mock_response.aiter_bytes = mock_aiter_bytes

    service = get_elevenlabs_tts_service()

    # Mock the client stream context manager
    class MockStreamContext:
        async def __aenter__(self):
            return mock_response

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch.object(
        service.client, "stream", return_value=MockStreamContext()
    ) as mock_stream:
        chunks = []
        async for chunk_data in service.synthesize_stream(
            "Hello stream", language="en"
        ):
            chunks.append(chunk_data["audio_bytes"])
            assert chunk_data["sample_rate"] == 24000

        mock_stream.assert_called_once()
        assert b"".join(chunks) == b"stream_chunk_123"


@pytest.mark.asyncio
async def test_elevenlabs_tts_circuit_breaker():
    # Setup
    settings.ELEVEN_LABS_API_KEY = "test_key"
    settings.ELEVENLABS_TTS_VOICE_ID = "voice_abc"

    service = get_elevenlabs_tts_service()
    # Reset breaker state
    service._breaker.failure_count = 0
    service._breaker.state = "closed"

    # Mock post to raise HTTPStatusError
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 500
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "500 Internal Server Error", request=None, response=mock_response
        )
    )

    with patch.object(service.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        with pytest.raises(httpx.HTTPStatusError):
            await service.synthesize("Hello fails", language="en")
