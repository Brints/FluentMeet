import uuid
from datetime import datetime

from app.kafka.schemas import BaseEvent, EmailEvent, EmailPayload


def test_base_event_serialization():
    payload = {"key": "value"}
    event = BaseEvent(event_type="test.event", payload=payload)

    assert isinstance(event.event_id, uuid.UUID)
    assert isinstance(event.timestamp, datetime)
    assert event.event_type == "test.event"
    assert event.payload == payload

    # Test JSON serialization via Pydantic
    dump = event.model_dump()
    assert dump["event_type"] == "test.event"
    assert dump["payload"] == payload


def test_email_event_validation():
    payload = EmailPayload(
        to_email="test@example.com",
        subject="Hello",
        template_name="welcome",
        template_data={"name": "User"},
    )
    event = EmailEvent(payload=payload)

    assert event.event_type == "email.dispatch"
    assert event.payload.to_email == "test@example.com"

    # Test model_validate
    event_dict = event.model_dump()
    validated_event = EmailEvent.model_validate(event_dict)
    assert validated_event.event_id == event.event_id
    assert validated_event.payload.to_email == "test@example.com"
