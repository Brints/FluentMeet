import urllib.parse
from typing import Any, cast

import httpx

from app.core.exceptions import BadGatewayException


class OAuthProviderException(BadGatewayException):
    def __init__(
        self, message: str = "Failed to authenticate with Google. Please try again."
    ) -> None:
        super().__init__(message=message, code="OAUTH_PROVIDER_ERROR")


class GoogleOAuthService:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.auth_url = "https://accounts.google.com/o/oauth2/v2/auth"
        self.token_url = "https://oauth2.googleapis.com/token"
        self.userinfo_url = "https://www.googleapis.com/oauth2/v3/userinfo"

    def build_auth_url(self, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "online",
            "prompt": "consent",
        }
        return f"{self.auth_url}?{urllib.parse.urlencode(params)}"

    async def exchange_code(self, code: str) -> str:
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
        }
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.token_url, data=data)
                response.raise_for_status()
                return cast(str, response.json()["access_token"])
            except httpx.HTTPError as err:
                raise OAuthProviderException(
                    "Failed to exchange authorization code with Google."
                ) from err

    async def get_user_info(self, access_token: str) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(self.userinfo_url, headers=headers)
                response.raise_for_status()
                return cast(dict[str, Any], response.json())
            except httpx.HTTPError as err:
                raise OAuthProviderException(
                    "Failed to fetch user profile from Google."
                ) from err
