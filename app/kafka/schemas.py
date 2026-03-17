import uuid
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class BaseEvent(BaseModel, Generic[T]):
    """
    Base class for all Kafka events.
    """

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: T


class DLQEvent(BaseModel):
    """
    Wrapper for events that failed processing and were routed to a Dead Letter Queue.
    Captures the original event alongside structured failure metadata.
    """

    original_event_id: uuid.UUID
    original_topic: str
    original_event: dict[str, Any]
    error_message: str
    failed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    retry_count: int


class EmailPayload(BaseModel):
    to: str
    subject: str
    template: str
    data: dict[str, Any] = Field(default_factory=dict)
    html_body: str | None = None


class EmailEvent(BaseEvent[EmailPayload]):
    event_type: str = "email.dispatch"


class MediaUploadPayload(BaseModel):
    user_id: int
    file_path: str
    file_type: str  # e.g., 'avatar', 'recording'
    metadata: dict[str, Any] = Field(default_factory=dict)


class MediaUploadEvent(BaseEvent[MediaUploadPayload]):
    event_type: str = "media.upload"
