"""Helper utilities for JWT generation and verification in tests."""


def decode_test_token(token: str) -> dict:
    """Mock/decode helper for test JWT tokens."""
    return {"sub": "test", "token": token}
