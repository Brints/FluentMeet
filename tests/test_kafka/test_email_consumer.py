from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.kafka.schemas import BaseEvent, EmailEvent, EmailPayload
from app.services.email_consumer import EmailConsumerWorker


@pytest.mark.asyncio
async def test_email_consumer_renders_template_when_html_missing() -> None:
    worker = EmailConsumerWorker(producer=MagicMock())
    render_mock = MagicMock(return_value="<html>rendered</html>")
    send_mock = AsyncMock()

    event = EmailEvent(
        payload=EmailPayload(
            to="user@example.com",
            subject="Verify",
            template="verification",
            data={"verification_link": "https://example.com"},
        )
    )

    worker._renderer.render = render_mock  # type: ignore[method-assign]
    worker._sender.send = send_mock  # type: ignore[method-assign]
    await worker.handle(cast(BaseEvent[Any], event))

    render_mock.assert_called_once_with(
        "verification", {"verification_link": "https://example.com"}
    )
    send_mock.assert_awaited_once_with(
        to="user@example.com",
        subject="Verify",
        html_body="<html>rendered</html>",
    )


@pytest.mark.asyncio
async def test_email_consumer_prefers_html_body_over_template_rendering() -> None:
    worker = EmailConsumerWorker(producer=MagicMock())
    render_mock = MagicMock()
    send_mock = AsyncMock()

    event = EmailEvent(
        payload=EmailPayload(
            to="user@example.com",
            subject="Reset Password",
            template="password_reset",
            data={"reset_link": "https://example.com"},
            html_body="<html>provided</html>",
        )
    )

    worker._renderer.render = render_mock  # type: ignore[method-assign]
    worker._sender.send = send_mock  # type: ignore[method-assign]
    await worker.handle(cast(BaseEvent[Any], event))

    render_mock.assert_not_called()
    send_mock.assert_awaited_once_with(
        to="user@example.com",
        subject="Reset Password",
        html_body="<html>provided</html>",
    )
