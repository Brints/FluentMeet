import logging
from typing import Any

from app.core.sanitize import sanitize_log_args
from app.kafka.manager import get_kafka_manager
from app.kafka.schemas import EmailEvent, EmailPayload
from app.kafka.topics import NOTIFICATIONS_EMAIL

logger = logging.getLogger(__name__)


class EmailProducerService:
    """Publishes email dispatch events to Kafka.

    Attributes:
        _topic: The target Kafka topic for email notifications.
    """

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
        """Schedule an email for dispatch by publishing it to Kafka.

        Args:
            to (str): Recipient email address.
            subject (str): Email subject.
            html_body (str | None): Raw HTML content, if pre-rendered.
            template_data (dict[str, Any]): Context variables for Jinja templating.
            template (str): The name of the template to be used if html_body
                is missing.
        """
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
        template_safe, to_safe = sanitize_log_args(template, to)
        logger.info("Queued email '%s' for %s", template_safe, to_safe)


_email_producer_service = EmailProducerService()


def get_email_producer_service() -> EmailProducerService:
    """Retrieve the singleton instance of EmailProducerService.

    Returns:
        EmailProducerService: The static service instance.
    """
    return _email_producer_service
