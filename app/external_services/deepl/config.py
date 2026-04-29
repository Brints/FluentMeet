"""DeepL provider configuration module.

Handles the secure retrieval of authentication headers required for the
DeepL mapping algorithms via the REST API.
"""

from app.core.config import settings


def get_deepl_headers() -> dict[str, str]:
    """Return authorization headers for the DeepL REST API.

    Returns:
        dict[str, str]: A dictionary containing the standard Authorization
        and Content-Type parameters required by the DeepL endpoint.

    Raises:
        RuntimeError: If DEEPL_API_KEY is missing from the environment.
    """
    if not settings.DEEPL_API_KEY:
        raise RuntimeError("DEEPL_API_KEY is not configured.")
    return {
        "Authorization": f"DeepL-Auth-Key {settings.DEEPL_API_KEY}",
        "Content-Type": "application/json",
    }
