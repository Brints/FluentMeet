import logging
from typing import Any

from app.kafka.manager import get_kafka_manager
from app.kafka.schemas import EmailEvent, EmailPayload
from app.kafka.topics import NOTIFICATIONS_EMAIL

logger = logging.getLogger(__name__)


class EmailProducerService:
    """Publishes email dispatch events to Kafka."""

    def __init__(self, topic: str = NOTIFICATIONS_EMAIL) -> None:
        self._topic = topic

    async def send_email(
        self,
        to: str,
        subject: str,
        html_body: str | None,
        template_data: dict[str, Any],
        template: str,
    ) -> None:
        payload = EmailPayload(
            to=to,
            subject=subject,
            template=template,
            data=template_data,
            html_body=html_body,
        )
        event = EmailEvent(payload=payload)

        kafka_manager = get_kafka_manager()
        await kafka_manager.producer.send(self._topic, event, key=to)
        logger.info("Queued email '%s' for %s", template, to)


_email_producer_service = EmailProducerService()


def get_email_producer_service() -> EmailProducerService:
    return _email_producer_service
