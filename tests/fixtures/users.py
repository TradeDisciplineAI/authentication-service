"""Reusable user fixtures."""

import pytest


@pytest.fixture
def test_user_data() -> dict[str, str]:
    """Placeholder fixture for reusable user creation data."""
    return {
        "username": "fixtureuser",
        "email": "fixture@example.com",
        "password": "StrongPassword123!",
    }
