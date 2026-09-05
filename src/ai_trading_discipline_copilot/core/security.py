# ------------------ Security Utilities Feature -----------------------
"""
Security helper functions for bcrypt password hashing, constant-time verification,
SHA-256 token hashing, and signed JWT access & refresh token generation/decoding.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
from jwt.exceptions import InvalidTokenError

from .config import get_settings

settings = get_settings()

_BCRYPT_ROUNDS = settings.bcrypt_rounds


# ------------------ Hash Password Function -----------------------
def hash_password(plain_password: str) -> str:
    """
    Hashes a plain-text password using bcrypt with salt rounds configured according to the application environment.
    Exceeding 72 bytes raises a ValueError to prevent bcrypt truncation vulnerabilities.
    """
    import os

    if len(plain_password.encode("utf-8")) > 72:
        raise ValueError("Password must not exceed 72 bytes")

    is_testing = (
        str(settings.app_env) == "test" or os.getenv("PYTEST_CURRENT_TEST") is not None
    )
    rounds = 4 if is_testing else _BCRYPT_ROUNDS
    salt = bcrypt.gensalt(rounds=rounds)
    hashed = bcrypt.hashpw(
        plain_password.encode("utf-8"),
        salt,
    )

    return hashed.decode("utf-8")


# ------------------ Verify Password Function -----------------------
def verify_password(
    plain_password: str,
    hashed_password: str,
) -> bool:
    """
    Verifies a plain-text password against a bcrypt hash in constant time.
    Returns True if the password is valid, False otherwise.
    """
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except ValueError:
        return False


# ------------------ Hash Refresh Token Function -----------------------
def hash_refresh_token(token: str) -> str:
    """
    Hashes a raw refresh token string using SHA-256 for secure database storage.
    """
    return hashlib.sha256(
        token.encode("utf-8"),
    ).hexdigest()


# ------------------ Verify Refresh Token Function -----------------------
def verify_refresh_token(
    refresh_token: str,
    token_hash: str,
) -> bool:
    """
    Verifies a raw refresh token against its stored SHA-256 hash.
    """
    return hash_refresh_token(refresh_token) == token_hash


# ------------------ Internal Token Creator Helper -----------------------
def _create_token(
    user_id: str,
    expires_delta: timedelta,
    token_type: str,
) -> tuple[str, str]:
    """
    Internal helper generating a signed JWT with expiration timestamp, issued timestamp,
    unique JTI, subject user_id, and specified token type (access or refresh).
    """
    now = datetime.now(UTC)
    jti = str(uuid.uuid4())

    payload = {
        "sub": user_id,
        "exp": now + expires_delta,
        "iat": now,
        "jti": jti,
        "type": token_type,
    }

    token = jwt.encode(
        payload,
        settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm,
    )

    return token, jti


# ------------------ Create Access Token Function -----------------------
def create_access_token(
    user_id: str,
) -> tuple[str, str]:
    """
    Creates a signed JWT access token for user authentication expiring according to settings.access_token_expire_minutes.
    """
    return _create_token(
        user_id=user_id,
        expires_delta=timedelta(
            minutes=settings.access_token_expire_minutes,
        ),
        token_type="access",
    )


# ------------------ Create Refresh Token Function -----------------------
def create_refresh_token(
    user_id: str,
) -> tuple[str, str]:
    """
    Creates a signed JWT refresh token for session continuation expiring according to settings.refresh_token_expire_days.
    """
    return _create_token(
        user_id=user_id,
        expires_delta=timedelta(
            days=settings.refresh_token_expire_days,
        ),
        token_type="refresh",
    )


# ------------------ Internal Token Decoder Helper -----------------------
def _decode_token(
    token: str,
    token_type: str,
) -> dict[str, Any] | None:
    """
    Internal helper verifying and decoding a signed JWT token string against algorithm and secret key.
    """
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=[settings.algorithm],
        )

        if payload.get("type") != token_type:
            return None

        return payload

    except InvalidTokenError:
        return None


# ------------------ Decode Access Token Function -----------------------
def decode_access_token(
    token: str,
) -> dict[str, Any] | None:
    """
    Decodes and validates a JWT access token, returning its payload dictionary or None if invalid.
    """
    return _decode_token(
        token=token,
        token_type="access",
    )


# ------------------ Decode Refresh Token Function -----------------------
def decode_refresh_token(
    token: str,
) -> dict[str, Any] | None:
    """
    Decodes and validates a JWT refresh token, returning its payload dictionary or None if invalid.
    """
    return _decode_token(
        token=token,
        token_type="refresh",
    )
