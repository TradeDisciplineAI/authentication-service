"""Password hashing and JWT token utilities."""

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

# 12 rounds is the industry-standard minimum for bcrypt (≈250ms per hash).
# Slower hashing directly resists brute-force attacks.
_BCRYPT_ROUNDS = settings.bcrypt_rounds


def hash_password(plain_password: str) -> str:
    """Return a bcrypt hash of the given plain-text password."""
    if len(plain_password.encode("utf-8")) > 72:
        raise ValueError("Password must not exceed 72 bytes")

    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    hashed = bcrypt.hashpw(
        plain_password.encode("utf-8"),
        salt,
    )

    return hashed.decode("utf-8")


def verify_password(
    plain_password: str,
    hashed_password: str,
) -> bool:
    """Return True if plain_password matches the stored bcrypt hash."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except ValueError:
        return False


def hash_refresh_token(token: str) -> str:
    """Return a SHA-256 hash of a refresh token."""

    return hashlib.sha256(
        token.encode("utf-8"),
    ).hexdigest()


def verify_refresh_token(
    refresh_token: str,
    token_hash: str,
) -> bool:
    """Verify a refresh token against its stored SHA-256 hash."""

    return hash_refresh_token(refresh_token) == token_hash


def _create_token(
    user_id: str,
    expires_delta: timedelta,
    token_type: str,
) -> tuple[str, str]:
    """Create a signed JWT and return the token with its JTI."""

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


def create_access_token(
    user_id: str,
) -> tuple[str, str]:
    """Create an access token."""

    return _create_token(
        user_id=user_id,
        expires_delta=timedelta(
            minutes=settings.access_token_expire_minutes,
        ),
        token_type="access",  # noqa: S106
    )


def create_refresh_token(
    user_id: str,
) -> tuple[str, str]:
    """Create a refresh token."""

    return _create_token(
        user_id=user_id,
        expires_delta=timedelta(
            days=settings.refresh_token_expire_days,
        ),
        token_type="refresh",  # noqa: S106
    )


def _decode_token(
    token: str,
    token_type: str,
) -> dict[str, Any] | None:
    """Verify and decode a JWT."""

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


def decode_access_token(
    token: str,
) -> dict[str, Any] | None:
    """Verify and decode an access token."""

    return _decode_token(
        token=token,
        token_type="access",  # noqa: S106
    )


def decode_refresh_token(
    token: str,
) -> dict[str, Any] | None:
    """Verify and decode a refresh token."""

    return _decode_token(
        token=token,
        token_type="refresh",  # noqa: S106
    )
