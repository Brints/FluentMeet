import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.modules.meeting.ws_dependencies import authenticate_ws

# Create a test client
client = TestClient(app)


@pytest.fixture(autouse=True)
def override_auth():
    app.dependency_overrides[authenticate_ws] = lambda: "user1"
    yield
    app.dependency_overrides = {}


@pytest.fixture
def mock_room_participant():
    with patch("app.modules.meeting.ws_router.assert_room_participant") as mock:
        mock.return_value = {"language": "es"}
        yield mock


@pytest.fixture
def mock_connection_manager():
    with patch("app.modules.meeting.ws_router.get_connection_manager") as mock_get_cm:
        cm = MagicMock()
        cm.connect = AsyncMock()
        cm.disconnect = MagicMock()
        cm.broadcast_to_room = AsyncMock()
        cm.send_to_user = AsyncMock()
        mock_get_cm.return_value = cm
        yield cm


@pytest.fixture
def mock_audio_ingest():
    with patch(
        "app.modules.meeting.ws_router.get_audio_ingest_service"
    ) as mock_get_ingest:
        ingest = MagicMock()
        ingest.reset_sequence = MagicMock()
        ingest.publish_audio_chunk = AsyncMock()
        mock_get_ingest.return_value = ingest
        yield ingest


@pytest.fixture
def mock_redis_client():
    with patch("app.modules.auth.token_store._get_redis_client") as mock_get_redis:
        redis_mock = MagicMock()
        pubsub_mock = MagicMock()

        async def mock_subscribe(*args, **kwargs):
            pass

        async def mock_unsubscribe(*args, **kwargs):
            pass

        async def mock_listen():
            if False:
                yield

        pubsub_mock.subscribe = mock_subscribe
        pubsub_mock.unsubscribe = mock_unsubscribe
        pubsub_mock.listen = mock_listen

        redis_mock.pubsub.return_value = pubsub_mock
        mock_get_redis.return_value = redis_mock
        yield redis_mock


@pytest.fixture
def mock_meeting_state():
    with patch(
        "app.modules.meeting.ws_router.MeetingStateService"
    ) as mock_service_class:
        service = MagicMock()
        service.get_participants = AsyncMock(return_value={})
        mock_service_class.return_value = service
        yield service


@pytest.mark.usefixtures("mock_room_participant", "mock_meeting_state")
def test_signaling_websocket(mock_connection_manager):
    # This will connect, send a text message, and then close
    with client.websocket_connect(
        "/api/v1/ws/signaling/room1?token=mock_token"
    ) as websocket:
        # Consume the initial existing_users message
        data = websocket.receive_json()
        assert data["type"] == "existing_users"

        websocket.send_text(json.dumps({"type": "offer", "target_user_id": "user2"}))
        # The connection manager's send_to_user should be called

    mock_connection_manager.connect.assert_called_once()
    mock_connection_manager.send_to_user.assert_called_once_with(
        "room1",
        "user2",
        {"type": "offer", "target_user_id": "user2", "from_user_id": "user1"},
    )
    mock_connection_manager.disconnect.assert_called_once_with("room1", "user1")
    assert mock_connection_manager.broadcast_to_room.call_count == 2
    # Verify second call is user_left
    mock_connection_manager.broadcast_to_room.assert_any_call(
        "room1", {"type": "user_left", "user_id": "user1"}, sender_id="user1"
    )


@pytest.mark.usefixtures("mock_room_participant", "mock_redis_client")
def test_audio_websocket_ingest(
    mock_audio_ingest,
):
    with client.websocket_connect(
        "/api/v1/ws/audio/room1?token=mock_token"
    ) as websocket:
        websocket.send_bytes(b"fake_audio_chunk")
        time.sleep(0.1)  # Yield to event loop for background tasks to process

    mock_audio_ingest.reset_sequence.assert_called_once_with("room1:user1")
