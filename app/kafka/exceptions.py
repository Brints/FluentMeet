from app.core.exceptions import FluentMeetException


class KafkaError(FluentMeetException):
    """Base exception for Kafka-related errors."""

    def __init__(self, message: str, code: str = "KAFKA_ERROR") -> None:
        super().__init__(status_code=500, code=code, message=message)


class KafkaConnectionError(KafkaError):
    def __init__(self, message: str = "Failed to connect to Kafka broker") -> None:
        super().__init__(message, code="KAFKA_CONNECTION_ERROR")


class KafkaPublishError(KafkaError):
    def __init__(self, message: str = "Failed to publish message to Kafka") -> None:
        super().__init__(message, code="KAFKA_PUBLISH_ERROR")


class KafkaConsumeError(KafkaError):
    def __init__(self, message: str = "Failed to consume message from Kafka") -> None:
        super().__init__(message, code="KAFKA_CONSUME_ERROR")
