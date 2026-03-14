import logging
from typing import Optional

from app.core.config import settings
from app.kafka.consumer import BaseConsumer
from app.kafka.producer import KafkaProducer

logger = logging.getLogger(__name__)


class KafkaManager:
    """
    Singleton manager responsible for Kafka producer and consumer lifecycles.

    Usage:
        manager = get_kafka_manager()
        manager.register_consumer(MyEmailConsumer())
        await manager.start()   # called from FastAPI lifespan
        await manager.stop()    # called from FastAPI lifespan
    """

    _instance: Optional["KafkaManager"] = None
    _initialized: bool = False

    def __new__(cls) -> "KafkaManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return

        self.producer = KafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS
        )
        self.consumers: list[BaseConsumer] = []
        self._initialized = True

    def register_consumer(self, consumer: BaseConsumer) -> None:
        """
        Register a consumer to be started when the manager starts.
        The producer is injected into the consumer at this point so it
        can access it for DLQ forwarding without a circular import.
        """
        consumer._producer = self.producer
        self.consumers.append(consumer)
        logger.info(f"Registered consumer for topic: '{consumer.topic}'")

    async def start(self) -> None:
        """Start the producer, then all registered consumers."""
        logger.info("Starting Kafka Manager...")
        await self.producer.start()

        for consumer in self.consumers:
            # Pass bootstrap_servers at start-time — consumers don't store it
            await consumer.start(bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS)

        logger.info(
            f"Kafka Manager started — {len(self.consumers)} consumer(s) running"
        )

    async def stop(self) -> None:
        """Stop all consumers first, then the producer."""
        logger.info("Stopping Kafka Manager...")

        for consumer in self.consumers:
            await consumer.stop()

        await self.producer.stop()
        logger.info("Kafka Manager stopped")

    async def health_check(self) -> dict:
        """
        Verify Kafka broker connectivity via a metadata probe.
        Uses the public producer.ping() API — no private attribute access.
        """
        if not self.producer.is_started:
            return {"status": "uninitialized", "details": "Producer not started"}

        try:
            await self.producer.ping()
            return {"status": "healthy"}
        except Exception as e:
            logger.error(f"Kafka health check failed: {e}")
            return {"status": "unhealthy", "error": str(e)}


def get_kafka_manager() -> KafkaManager:
    """Return the KafkaManager singleton."""
    return KafkaManager()
