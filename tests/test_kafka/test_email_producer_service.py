from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.services.email_producer import EmailProducerService


@pytest.mark.asyncio
async def test_send_email_publishes_email_event() -> None:
    producer = Mock()
    producer.send = AsyncMock()

    kafka_manager = Mock()
    kafka_manager.producer = producer

    service = EmailProducerService()
    with patch(
        "app.services.email_producer.get_kafka_manager",
        return_value=kafka_manager,
    ):
        await service.send_email(
            to="user@example.com",
            subject="Verify account",
            html_body=None,
            template_data={"verification_link": "https://example.com/verify"},
            template="verification",
        )

    producer.send.assert_awaited_once()
    args, kwargs = producer.send.call_args
    assert args[0] == "notifications.email"
    assert kwargs["key"] == "user@example.com"

    event = args[1]
    assert event.payload.to == "user@example.com"
    assert event.payload.template == "verification"
    assert event.payload.data["verification_link"].startswith("https://")
