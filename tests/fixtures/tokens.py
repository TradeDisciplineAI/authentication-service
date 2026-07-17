"""JWT and refresh token fixtures."""

import pytest


@pytest.fixture
def mock_jwt_token() -> str:
    """Placeholder fixture for JWT token string."""
    return "mock.jwt.token"


@pytest.fixture
def mock_refresh_token() -> str:
    """Placeholder fixture for refresh token string."""
    return "mock-refresh-token-uuid"
