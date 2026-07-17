from datetime import UTC, datetime, timedelta

import jwt
import pytest

from ai_trading_discipline_copilot.core.config import get_settings
from ai_trading_discipline_copilot.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
    verify_refresh_token,
)

settings = get_settings()


def test_hash_password_success() -> None:
    # Arrange & Act
    password = "MySecurePassword123"
    hashed = hash_password(password)

    # Assert
    assert hashed != password
    assert hashed.startswith("$2b$")  # bcrypt prefix


def test_hash_password_too_long() -> None:
    # Arrange
    long_password = "a" * 73

    # Act & Assert
    with pytest.raises(ValueError, match="Password must not exceed 72 bytes"):
        hash_password(long_password)


def test_verify_password_success() -> None:
    # Arrange
    password = "MySecurePassword123"
    hashed = hash_password(password)

    # Act & Assert
    assert verify_password(password, hashed) is True


def test_verify_password_failure() -> None:
    # Arrange
    password = "MySecurePassword123"
    hashed = hash_password(password)

    # Act & Assert
    assert verify_password("WrongPassword123", hashed) is False


def test_verify_password_invalid_hash() -> None:
    # Arrange
    password = "MySecurePassword123"
    invalid_hash = "not-a-valid-bcrypt-hash"

    # Act & Assert
    # bcrypt.checkpw should raise ValueError, which is caught and returns False
    assert verify_password(password, invalid_hash) is False


def test_hash_refresh_token_success() -> None:
    # Arrange
    token = "some-random-uuid-refresh-token"

    # Act
    hashed = hash_refresh_token(token)

    # Assert
    # Expected SHA-256 hash length is 64 characters
    assert len(hashed) == 64
    assert hashed != token


def test_verify_refresh_token() -> None:
    # Arrange
    token = "some-random-uuid-refresh-token"
    hashed = hash_refresh_token(token)

    # Act & Assert
    assert verify_refresh_token(token, hashed) is True
    assert verify_refresh_token("wrong-token", hashed) is False


def test_create_access_token() -> None:
    # Arrange
    user_id = "12345678-1234-5678-1234-567812345678"

    # Act
    token, jti = create_access_token(user_id)

    # Assert
    assert token is not None
    assert isinstance(token, str)
    assert jti is not None
    assert isinstance(jti, str)

    # Decode and check claims
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == user_id
    assert payload["type"] == "access"
    assert payload["jti"] == jti
    assert "exp" in payload
    assert "iat" in payload


def test_create_refresh_token() -> None:
    # Arrange
    user_id = "12345678-1234-5678-1234-567812345678"

    # Act
    token, jti = create_refresh_token(user_id)

    # Assert
    assert token is not None
    assert isinstance(token, str)
    assert jti is not None
    assert isinstance(jti, str)

    # Decode and check claims
    payload = decode_refresh_token(token)
    assert payload is not None
    assert payload["sub"] == user_id
    assert payload["type"] == "refresh"
    assert payload["jti"] == jti
    assert "exp" in payload
    assert "iat" in payload


def test_decode_token_invalid_signature() -> None:
    # Arrange
    user_id = "12345678-1234-5678-1234-567812345678"
    token, _ = create_access_token(user_id)
    # Alter token to invalidate signature
    invalid_token = token + "corrupted"

    # Act
    decoded = decode_access_token(invalid_token)

    # Assert
    assert decoded is None


def test_decode_token_invalid_type() -> None:
    # Arrange
    user_id = "12345678-1234-5678-1234-567812345678"
    token, _ = create_access_token(user_id)

    # Act & Assert
    # Trying to decode access token as a refresh token should return None due to mismatch
    assert decode_refresh_token(token) is None


def test_decode_token_expired() -> None:
    # Arrange
    user_id = "12345678-1234-5678-1234-567812345678"
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "exp": now - timedelta(seconds=1),  # Expired 1 second ago
        "iat": now - timedelta(seconds=10),
        "jti": "some-jti",
        "type": "access",
    }
    expired_token = jwt.encode(
        payload,
        settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm,
    )

    # Act
    decoded = decode_access_token(expired_token)

    # Assert
    assert decoded is None
