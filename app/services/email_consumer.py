import logging
from pathlib import Path
from typing import Any

import httpx
from jinja2 import Environment, FileSystemLoader, TemplateNotFound

from app.core.config import settings
from app.core.sanitize import sanitize_log_args
from app.kafka.consumer import BaseConsumer
from app.kafka.schemas import BaseEvent, EmailEvent
from app.kafka.topics import NOTIFICATIONS_EMAIL

logger = logging.getLogger(__name__)


class TransientEmailDeliveryError(Exception):
    """Signals failures that should trigger Kafka retries."""


class EmailTemplateRenderer:
    def __init__(self) -> None:
        templates_root = Path(__file__).resolve().parent.parent / "templates" / "email"
        self._environment = Environment(
            loader=FileSystemLoader(str(templates_root)),
            autoescape=True,
        )

    def render(self, template_name: str, data: dict[str, object]) -> str:
        try:
            template = self._environment.get_template(f"{template_name}.html")
        except TemplateNotFound:
            template_name_safe = sanitize_log_args(template_name)[0]
            logger.warning(
                "Template '%s' is missing, falling back to raw html",
                template_name_safe,
            )
            return ""
        return template.render(**data)


class MailgunEmailSender:
    """Sends emails via Mailgun's /messages endpoint."""

    def __init__(
        self, timeout_seconds: float = settings.MAILGUN_TIMEOUT_SECONDS
    ) -> None:
        self._timeout_seconds = timeout_seconds

    async def send(self, to: str, subject: str, html_body: str) -> None:
        if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
            logger.warning("Mailgun credentials not configured; skipping dispatch")
            return

        endpoint = f"https://api.mailgun.net/v3/{settings.MAILGUN_DOMAIN}/messages"
        payload = {
            "from": settings.MAILGUN_FROM_ADDRESS,
            "to": to,
            "subject": subject,
            "html": html_body,
        }

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(
                endpoint,
                data=payload,
                auth=("api", settings.MAILGUN_API_KEY),
            )

        if response.status_code in {408, 425, 429} or response.status_code >= 500:
            raise TransientEmailDeliveryError(
                f"Mailgun transient error ({response.status_code}): {response.text}"
            )
        if response.status_code >= 400:
            status_safe, response_text_safe = sanitize_log_args(
                response.status_code, response.text
            )
            logger.error(
                "Mailgun rejected email with status %s: %s",
                status_safe,
                response_text_safe,
            )
            return


class EmailConsumerWorker(BaseConsumer):
    topic = NOTIFICATIONS_EMAIL
    group_id = settings.KAFKA_EMAIL_CONSUMER_GROUP_ID
    event_schema = EmailEvent

    def __init__(self, producer: object) -> None:
        super().__init__(producer=producer)
        self._sender = MailgunEmailSender()
        self._renderer = EmailTemplateRenderer()

    async def handle(self, event: BaseEvent[Any]) -> None:
        email_event = EmailEvent.model_validate(event.model_dump())
        html_body = email_event.payload.html_body
        if not html_body:
            html_body = self._renderer.render(
                email_event.payload.template,
                email_event.payload.data,
            )

        if not html_body:
            event_id_safe = sanitize_log_args(email_event.event_id)[0]
            logger.error("No html body could be rendered for event %s", event_id_safe)
            return

        await self._sender.send(
            to=email_event.payload.to,
            subject=email_event.payload.subject,
            html_body=html_body,
        )
        event_id_safe, recipient_safe = sanitize_log_args(
            email_event.event_id, email_event.payload.to
        )
        logger.info(
            "Dispatched email event %s to %s",
            event_id_safe,
            recipient_safe,
        )
