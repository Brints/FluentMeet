"""Unit tests for ``app.core.security.SecurityService``."""

from jose import jwt

from app.core.config import settings
from app.core.security import SecurityService


class TestVerifyPassword:
    """Test password hashing and verification."""

    def setup_method(self) -> None:
        self.svc = SecurityService()

    def test_correct_password_returns_true(self) -> None:
        hashed = self.svc.hash_password("MyStr0ngP@ss!")
        assert self.svc.verify_password("MyStr0ngP@ss!", hashed) is True

    def test_wrong_password_returns_false(self) -> None:
        hashed = self.svc.hash_password("MyStr0ngP@ss!")
        assert self.svc.verify_password("WrongPassword!", hashed) is False

    def test_hash_is_not_plaintext(self) -> None:
        hashed = self.svc.hash_password("MyStr0ngP@ss!")
        assert hashed != "MyStr0ngP@ss!"
        assert hashed.startswith("$2")


class TestCreateAccessToken:
    """Test JWT access-token generation."""

    def setup_method(self) -> None:
        self.svc = SecurityService()

    def test_returns_decodable_jwt_with_correct_claims(self) -> None:
        token, _expires_in = self.svc.create_access_token(
            email="user@example.com",
            jti="test-jti-123",
        )

        decoded = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        assert decoded["sub"] == "user@example.com"
        assert decoded["jti"] == "test-jti-123"
        assert decoded["type"] == "access"
        assert "exp" in decoded

    def test_expires_in_matches_config(self) -> None:
        _token, expires_in = self.svc.create_access_token(email="user@example.com")
        assert expires_in == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

    def test_auto_generates_jti_when_omitted(self) -> None:
        token, _ = self.svc.create_access_token(email="user@example.com")
        decoded = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        assert decoded["jti"]  # non-empty


class TestCreateRefreshToken:
    """Test JWT refresh-token generation."""

    def setup_method(self) -> None:
        self.svc = SecurityService()

    def test_returns_decodable_jwt_with_correct_claims(self) -> None:
        token, jti, _ttl = self.svc.create_refresh_token(
            email="user@example.com",
            jti="refresh-jti-456",
        )

        decoded = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        assert decoded["sub"] == "user@example.com"
        assert decoded["jti"] == "refresh-jti-456"
        assert decoded["type"] == "refresh"
        assert "exp" in decoded
        assert jti == "refresh-jti-456"

    def test_ttl_matches_config(self) -> None:
        _token, _jti, ttl = self.svc.create_refresh_token(email="user@example.com")
        assert ttl == settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400

    def test_auto_generates_jti_when_omitted(self) -> None:
        token, jti, _ = self.svc.create_refresh_token(email="user@example.com")
        assert jti  # non-empty
        decoded = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        assert decoded["jti"] == jti
