"""Authentication fixtures."""

import pytest
from httpx import AsyncClient


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Placeholder fixture for authentication headers."""
    return {"Authorization": "Bearer placeholder-token"}


@pytest.fixture
def authenticated_client(client: AsyncClient) -> AsyncClient:
    """Placeholder fixture for an authenticated API client."""
    return client
