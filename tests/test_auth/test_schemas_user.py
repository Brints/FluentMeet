import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.auth.schemas import SupportedLanguage, UserResponse


def test_user_response_can_validate_from_attributes() -> None:
    mock_id = uuid.uuid4()
    source = SimpleNamespace(
        id=mock_id,
        email="person@example.com",
        full_name="Test Person",
        speaking_language="en",
        listening_language="fr",
        is_active=True,
        is_verified=False,
        user_role="user",
        created_at=datetime.now(UTC),
    )

    result = UserResponse.model_validate(source)

    assert result.id == mock_id
    assert result.email == "person@example.com"
    assert result.speaking_language == SupportedLanguage.ENGLISH
    assert result.listening_language == SupportedLanguage.FRENCH
