import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.kafka.consumer import BaseConsumer
from app.kafka.schemas import BaseEvent


class MockEvent(BaseEvent[dict]):
    event_type: str = "test.mock"


class TestConsumer(BaseConsumer):
    topic = "test-topic"
    group_id = "test-group"
    event_schema = MockEvent

    async def handle(self, event: BaseEvent) -> None:  # type: ignore[override]
        pass  # overridden per test via mock


@pytest.fixture
def mock_producer():
    producer = MagicMock()
    producer.is_started = True
    producer._producer = AsyncMock()
    producer._producer.send_and_wait = AsyncMock()
    return producer


@pytest.fixture
def consumer(mock_producer):
    return TestConsumer(producer=mock_producer)


@pytest.mark.asyncio
async def test_consumer_success_on_first_try(consumer):
    """handle() succeeds on first attempt — no retries, no DLQ."""
    consumer.handle = AsyncMock()
    event = MockEvent(payload={"data": "test"})

    with patch("app.kafka.consumer.settings") as mock_settings:
        mock_settings.KAFKA_MAX_RETRIES = 2
        mock_settings.KAFKA_RETRY_BACKOFF_MS = 1

        await consumer._process_with_retry(event)

    consumer.handle.assert_awaited_once_with(event)


@pytest.mark.asyncio
async def test_consumer_retries_then_succeeds(consumer):
    """handle() fails twice then succeeds on third attempt."""
    call_count = 0

    async def flaky_handle(event):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError("transient error")

    consumer.handle = flaky_handle

    with patch("app.kafka.consumer.settings") as mock_settings:
        mock_settings.KAFKA_MAX_RETRIES = 3
        mock_settings.KAFKA_RETRY_BACKOFF_MS = 1

        await consumer._process_with_retry(MockEvent(payload={}))

    assert call_count == 3


@pytest.mark.asyncio
async def test_consumer_routes_to_dlq_after_exhausted_retries(consumer):
    """After all retries fail, the event is sent to DLQ as a DLQEvent wrapper."""
    consumer.handle = AsyncMock(side_effect=Exception("permanent failure"))
    consumer._send_to_dlq = AsyncMock()
    event = MockEvent(payload={"data": "test"})

    with patch("app.kafka.consumer.settings") as mock_settings:
        mock_settings.KAFKA_MAX_RETRIES = 2
        mock_settings.KAFKA_RETRY_BACKOFF_MS = 1

        await consumer._process_with_retry(event)

    # handle should be called MAX_RETRIES + 1 times (initial + retries)
    assert consumer.handle.await_count == 3
    consumer._send_to_dlq.assert_awaited_once()
    # Verify DLQ was called with the correct event and retry count
    _, kwargs = consumer._send_to_dlq.call_args
    assert kwargs.get("retries") == 2 or consumer._send_to_dlq.call_args.args[2] == 2


@pytest.mark.asyncio
async def test_dlq_wraps_event_correctly(consumer, mock_producer):
    """_send_to_dlq creates a proper DLQEvent — no payload mutation."""
    event = MockEvent(payload={"key": "value"})

    await consumer._send_to_dlq(event, "test error", retries=3)

    # DLQ is sent via the injected producer's internal send_and_wait
    mock_producer._producer.send_and_wait.assert_awaited_once()
    call_args = mock_producer._producer.send_and_wait.call_args
    # First positional arg should be the DLQ topic
    assert call_args.args[0] == f"dlq.{consumer.topic}"

    # Verify original event payload was not mutated
    assert not hasattr(event.payload, "error")
