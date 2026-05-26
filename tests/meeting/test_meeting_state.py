"""Unit tests for MeetingStateService language validation."""

from unittest.mock import AsyncMock

import pytest

from app.modules.meeting.state import MeetingStateService


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Mock Redis client."""
    redis = AsyncMock()
    redis.hset = AsyncMock(return_value=1)
    redis.hget = AsyncMock(return_value=None)
    redis.hdel = AsyncMock(return_value=1)
    return redis


@pytest.fixture
def meeting_state(mock_redis: AsyncMock) -> MeetingStateService:
    return MeetingStateService(redis_client=mock_redis)


@pytest.mark.asyncio
async def test_add_participant_valid_languages(
    meeting_state: MeetingStateService, mock_redis: AsyncMock
) -> None:
    # Test valid language code validation (case-insensitive and whitespace stripped)
    await meeting_state.add_participant(
        room_code="testroom",
        user_id="user123",
        language=" EN ",
        speaking_language="de",
    )
    mock_redis.hset.assert_called_once()
    # Check that it serialized correctly with normalized "en" and "de"
    args, kwargs = mock_redis.hset.call_args
    assert kwargs.get("name") or args[0]
    # Verify normalization worked
    import json

    val = kwargs.get("value") or args[2]
    parsed = json.loads(val)
    assert parsed["language"] == "en"
    assert parsed["speaking_language"] == "de"


@pytest.mark.asyncio
async def test_add_participant_invalid_listening_language(
    meeting_state: MeetingStateService,
) -> None:
    # Test invalid listening language raises ValueError
    with pytest.raises(ValueError, match="Unsupported language code: xx"):
        await meeting_state.add_participant(
            room_code="testroom",
            user_id="user123",
            language="xx",
            speaking_language="en",
        )


@pytest.mark.asyncio
async def test_add_participant_invalid_speaking_language(
    meeting_state: MeetingStateService,
) -> None:
    # Test invalid speaking language raises ValueError
    with pytest.raises(ValueError, match="Unsupported language code: yy"):
        await meeting_state.add_participant(
            room_code="testroom",
            user_id="user123",
            language="en",
            speaking_language="yy",
        )


@pytest.mark.asyncio
async def test_add_to_lobby_valid_languages(
    meeting_state: MeetingStateService, mock_redis: AsyncMock
) -> None:
    # Test valid lobby addition
    await meeting_state.add_to_lobby(
        room_code="testroom",
        user_id="user123",
        display_name="Test User",
        language="fr",
        speaking_language=" ES ",
    )
    mock_redis.hset.assert_called_once()
    args, kwargs = mock_redis.hset.call_args
    import json

    val = kwargs.get("value") or args[2]
    parsed = json.loads(val)
    assert parsed["language"] == "fr"
    assert parsed["speaking_language"] == "es"


@pytest.mark.asyncio
async def test_add_to_lobby_invalid_listening_language(
    meeting_state: MeetingStateService,
) -> None:
    with pytest.raises(ValueError, match="Unsupported language code: invalid"):
        await meeting_state.add_to_lobby(
            room_code="testroom",
            user_id="user123",
            display_name="Test User",
            language="invalid",
            speaking_language="en",
        )


@pytest.mark.asyncio
async def test_add_to_lobby_invalid_speaking_language(
    meeting_state: MeetingStateService,
) -> None:
    with pytest.raises(ValueError, match="Unsupported language code: invalid"):
        await meeting_state.add_to_lobby(
            room_code="testroom",
            user_id="user123",
            display_name="Test User",
            language="en",
            speaking_language="invalid",
        )
