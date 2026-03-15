from datetime import UTC, datetime
from types import SimpleNamespace

from app.schemas.user import SupportedLanguage, UserResponse


def test_user_response_can_validate_from_attributes() -> None:
    source = SimpleNamespace(
        id=123,
        email="person@example.com",
        full_name="Test Person",
        speaking_language="en",
        listening_language="fr",
        is_active=True,
        is_verified=False,
        created_at=datetime.now(UTC),
    )

    result = UserResponse.model_validate(source)

    assert result.id == 123
    assert result.email == "person@example.com"
    assert result.speaking_language == SupportedLanguage.ENGLISH
    assert result.listening_language == SupportedLanguage.FRENCH
