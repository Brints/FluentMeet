"""Kafka Producer module.

This module provides a wrapper around AIOKafkaProducer to handle robust
asynchronous message publishing and automatic schema serialization.
"""

import json
import logging
from typing import Any

from aiokafka import AIOKafkaProducer  # type: ignore[import-untyped]

from app.core.config import settings
from app.core.sanitize import sanitize_log_args
from app.kafka.exceptions import KafkaPublishError
from app.kafka.schemas import BaseEvent

logger = logging.getLogger(__name__)


class KafkaProducer:
    """Wrapper around AIOKafkaProducer with Pydantic serialization.

    Provides high-level methods to serialize and publish `BaseEvent`
    payloads directly into Kafka topics.
    """

    def __init__(self, bootstrap_servers: str):
        self._producer: AIOKafkaProducer | None = None
        self._bootstrap_servers = bootstrap_servers

    @property
    def is_started(self) -> bool:
        """Returns True if the underlying producer is running."""
        return self._producer is not None

    async def start(self) -> None:
        """Start the Kafka producer."""
        if self._producer is not None:
            return

        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap_servers,
            acks=settings.KAFKA_PRODUCER_ACK,
            value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
        )
        await self._producer.start()
        logger.info("Kafka producer started")

    async def stop(self) -> None:
        """Stop the Kafka producer."""
        if self._producer:
            await self._producer.stop()
            self._producer = None
            logger.info("Kafka producer stopped")

    async def ping(self) -> None:
        """
        Verify broker connectivity by fetching cluster metadata.
        Raises an exception if the broker is unreachable.
        """
        if not self._producer:
            raise KafkaPublishError("Kafka producer is not started")
        await self._producer.client.force_metadata_update()

    async def send(
        self, topic: str, event: BaseEvent[Any], key: str | None = None
    ) -> None:
        """
        Serialize and send an event to a Kafka topic.
        """
        if not self._producer:
            raise KafkaPublishError("Kafka producer is not started")

        try:
            message_dict = event.model_dump()
            await self._producer.send_and_wait(
                topic, value=message_dict, key=key.encode("utf-8") if key else None
            )
            event_id_safe, topic_safe = sanitize_log_args(event.event_id, topic)
            logger.debug("Event %s sent to topic %s", event_id_safe, topic_safe)
        except KafkaPublishError:
            raise
        except Exception as e:
            topic_safe = sanitize_log_args(topic)[0]
            logger.exception("Failed to publish event to %s", topic_safe)
            raise KafkaPublishError(f"Error publishing to {topic}: {e!s}") from e
