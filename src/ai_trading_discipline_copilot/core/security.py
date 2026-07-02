"""Password hashing and JWT token utilities."""

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from jwt.exceptions import InvalidTokenError

from .config import get_settings

settings = get_settings()

# 12 rounds is the industry-standard minimum for bcrypt (≈250ms per hash).
# Slower hashing directly resists brute-force attacks.
_BCRYPT_ROUNDS = 12


def hash_password(plain_password: str) -> str:
    """Return a bcrypt hash of the given plain-text password."""
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Return True if plain_password matches the stored bcrypt hash."""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def create_access_token(user_id: str) -> str:
    """Return a signed JWT access token for the given user ID.

    Payload: sub (user UUID), exp (expiry), iat (issued-at).
    Never include sensitive fields such as email or roles in the payload.
    """
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=settings.access_token_expire_minutes)

    payload: dict[str, str | datetime] = {
        "sub": user_id,
        "exp": expire,
        "iat": now,
        # Explicit type claim prevents token confusion attacks
        # if refresh tokens are added in the future.
        "type": "access",
    }

    return jwt.encode(
        payload,
        settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm,
    )


def decode_access_token(token: str) -> str | None:
    """Verify and decode a JWT. Return the user_id or None on any failure.

    Returns None instead of raising so the caller decides how to handle
    invalid or expired tokens.
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=[settings.algorithm],
        )
        user_id: str | None = payload.get("sub")
        if payload.get("type") != "access":
            return None
        return user_id
    except InvalidTokenError:
        return None
