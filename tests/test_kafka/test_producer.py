from unittest.mock import AsyncMock, patch

import pytest

from app.kafka.producer import KafkaProducer
from app.kafka.schemas import BaseEvent


@pytest.mark.asyncio
async def test_producer_send_serializes_event():
    """send() correctly serializes a Pydantic event and routes it to the topic."""
    with patch("app.kafka.producer.AIOKafkaProducer") as mock_cls:
        mock_internal = AsyncMock()
        mock_cls.return_value = mock_internal

        producer = KafkaProducer(bootstrap_servers="localhost:9092")
        await producer.start()

        assert producer.is_started

        event = BaseEvent(event_type="test.event", payload={"foo": "bar"})
        await producer.send("test-topic", event)

        mock_internal.send_and_wait.assert_awaited_once()
        args, kwargs = mock_internal.send_and_wait.call_args
        assert args[0] == "test-topic"
        assert kwargs["value"]["event_type"] == "test.event"
        assert kwargs["value"]["payload"] == {"foo": "bar"}

        await producer.stop()
        assert not producer.is_started
        mock_internal.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_producer_ping_calls_metadata_update():
    """ping() delegates to force_metadata_update on the aiokafka client."""
    with patch("app.kafka.producer.AIOKafkaProducer") as mock_cls:
        mock_internal = AsyncMock()
        mock_internal.client = AsyncMock()
        mock_cls.return_value = mock_internal

        producer = KafkaProducer(bootstrap_servers="localhost:9092")
        await producer.start()
        await producer.ping()

        mock_internal.client.force_metadata_update.assert_awaited_once()


@pytest.mark.asyncio
async def test_producer_not_started_raises():
    """send() and ping() raise KafkaPublishError if the producer hasn't started."""
    from app.kafka.exceptions import KafkaPublishError

    producer = KafkaProducer(bootstrap_servers="localhost:9092")

    with pytest.raises(KafkaPublishError):
        await producer.send("any-topic", BaseEvent(event_type="e", payload={}))

    with pytest.raises(KafkaPublishError):
        await producer.ping()
