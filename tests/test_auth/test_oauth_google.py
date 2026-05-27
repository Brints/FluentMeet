import json
import uuid
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.modules.auth.dependencies import get_auth_service, get_google_oauth_service
from app.modules.auth.oauth_google import GoogleOAuthService
from app.modules.auth.schemas import LoginResponse

client = TestClient(app)


@pytest.fixture(autouse=True)
def override_oauth_service():
    app.dependency_overrides[get_google_oauth_service] = lambda: GoogleOAuthService(
        "id", "secret", "uri"
    )
    yield
    app.dependency_overrides.pop(get_google_oauth_service, None)


def test_google_login_endpoint() -> None:
    with patch("app.modules.auth.token_store._get_redis_client") as mock_redis:
        mock_redis_instance = AsyncMock()
        mock_redis.return_value = mock_redis_instance

        response = client.get("/api/v1/auth/google/login", follow_redirects=False)
        assert response.status_code == 302
        assert "accounts.google.com" in response.headers["location"]

        # Verify state is stored in redis
        url = response.headers["location"]
        parsed_url = urlparse(url)
        qs = parse_qs(parsed_url.query)
        state = qs.get("state", [""])[0]

        mock_redis_instance.set.assert_called_once()
        assert f"oauth_state:{state}" in mock_redis_instance.set.call_args[0][0]


@patch("app.modules.auth.oauth_google.GoogleOAuthService.exchange_code")
@patch("app.modules.auth.oauth_google.GoogleOAuthService.get_user_info")
@patch("app.modules.auth.token_store._get_redis_client")
def test_google_callback_invalid_state(
    mock_redis,
    mock_get_user_info: AsyncMock,  # noqa: ARG001
    mock_exchange_code: AsyncMock,  # noqa: ARG001
) -> None:
    mock_redis_instance = AsyncMock()
    mock_redis_instance.exists.return_value = False
    mock_redis.return_value = mock_redis_instance

    response = client.get(
        "/api/v1/auth/google/callback?code=mockcode&state=invalidstate"
    )
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_OAUTH_STATE"


@patch("app.modules.auth.oauth_google.GoogleOAuthService.exchange_code")
@patch("app.modules.auth.oauth_google.GoogleOAuthService.get_user_info")
@patch("app.modules.auth.token_store._get_redis_client")
def test_google_callback_unverified_email(
    mock_redis,
    mock_get_user_info: AsyncMock,
    mock_exchange_code: AsyncMock,
) -> None:
    mock_redis_instance = AsyncMock()
    mock_redis_instance.exists.return_value = True
    mock_redis.return_value = mock_redis_instance

    mock_exchange_code.return_value = "mock_token"
    mock_get_user_info.return_value = {
        "email": "user@google.com",
        "email_verified": False,
        "sub": "google123",
        "name": "Google User",
        "picture": "http://example.com/avatar.png",
    }

    response = client.get(
        "/api/v1/auth/google/callback?code=mockcode&state=validstate",
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_OAUTH_PROFILE"


@patch("app.modules.auth.oauth_google.GoogleOAuthService.exchange_code")
@patch("app.modules.auth.oauth_google.GoogleOAuthService.get_user_info")
@patch("app.modules.auth.token_store._get_redis_client")
def test_google_callback_and_exchange_success(
    mock_redis,
    mock_get_user_info: AsyncMock,
    mock_exchange_code: AsyncMock,
) -> None:
    mock_redis_instance = AsyncMock()
    mock_redis_instance.exists.return_value = True
    mock_redis.return_value = mock_redis_instance

    mock_exchange_code.return_value = "mock_token"
    mock_get_user_info.return_value = {
        "email": "user@google.com",
        "email_verified": True,
        "sub": "google123",
        "name": "Google User",
        "picture": "http://example.com/avatar.png",
    }

    mock_auth_svc = AsyncMock()
    mock_auth_svc.resolve_oauth_user.return_value = (
        LoginResponse(
            access_token="test_access_jwt",
            user_id=uuid.uuid4(),
            token_type="bearer",
            expires_in=3600,
        ),
        "test_refresh_jwt",
        86400,
    )

    app.dependency_overrides[get_auth_service] = lambda: mock_auth_svc

    # 1. Trigger the callback
    response = client.get(
        "/api/v1/auth/google/callback?code=mockcode&state=validstate",
        follow_redirects=False,
    )

    assert response.status_code == 302
    redirect_url = response.headers["location"]
    assert "oauth-callback?code=" in redirect_url

    parsed_url = urlparse(redirect_url)
    qs = parse_qs(parsed_url.query)
    exchange_code = qs.get("code", [""])[0]
    assert exchange_code != ""

    # Verify state was deleted
    mock_redis_instance.delete.assert_any_call("oauth_state:validstate")

    # Verify oauth_exchange was set in Redis
    mock_redis_instance.set.assert_any_call(
        f"oauth_exchange:{exchange_code}",
        pytest.approx(
            json.dumps(
                {
                    "access_token": "test_access_jwt",
                    "user_id": str(
                        mock_auth_svc.resolve_oauth_user.return_value[0].user_id
                    ),
                    "token_type": "bearer",
                    "expires_in": 3600,
                    "refresh_token": "test_refresh_jwt",
                    "refresh_ttl": 86400,
                }
            )
        ),
        ex=300,
    )

    # 2. Mock Redis behavior for the exchange request
    mock_redis_instance.getdel.return_value = json.dumps(
        {
            "access_token": "test_access_jwt",
            "user_id": str(mock_auth_svc.resolve_oauth_user.return_value[0].user_id),
            "token_type": "bearer",
            "expires_in": 3600,
            "refresh_token": "test_refresh_jwt",
            "refresh_ttl": 86400,
        }
    )

    # 3. Call the exchange endpoint
    exchange_response = client.post(
        "/api/v1/auth/google/exchange",
        json={"code": exchange_code},
    )

    app.dependency_overrides.clear()

    assert exchange_response.status_code == 200
    assert exchange_response.json()["access_token"] == "test_access_jwt"
    assert exchange_response.json()["token_type"] == "bearer"
    assert "refresh_token" in exchange_response.cookies
    assert exchange_response.cookies["refresh_token"] == "test_refresh_jwt"

    # Verify atomic getdel was called for the exchange code
    mock_redis_instance.getdel.assert_called_once_with(
        f"oauth_exchange:{exchange_code}"
    )
