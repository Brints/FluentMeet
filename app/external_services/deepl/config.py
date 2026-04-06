"""DeepL provider configuration."""

from app.core.config import settings


def get_deepl_headers() -> dict[str, str]:
    """Return authorization headers for the DeepL REST API."""
    if not settings.DEEPL_API_KEY:
        raise RuntimeError("DEEPL_API_KEY is not configured.")
    return {
        "Authorization": f"DeepL-Auth-Key {settings.DEEPL_API_KEY}",
        "Content-Type": "application/json",
    }
