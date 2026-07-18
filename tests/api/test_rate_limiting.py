from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from ai_trading_discipline_copilot.core.config import get_settings
from ai_trading_discipline_copilot.core.security import hash_password
from ai_trading_discipline_copilot.models.user import User

settings = get_settings()
TEST_PASSWORD = "StrongPass1!"  # noqa: S105
WRONG_PASSWORD = "WrongPass1!"  # noqa: S105


@pytest.mark.anyio
async def test_account_lockout_after_max_failed_logins(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test that an account is locked after max failed login attempts."""
    # Create verified user
    user = User(
        username="lockoutuser",
        email="lockout@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()

    # Attempt failed logins up to max_login_attempts
    for _ in range(settings.max_login_attempts):
        response = await client.post(
            "/auth/login",
            data={"username": "lockoutuser", "password": WRONG_PASSWORD},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid username or password"

    # Refresh user from DB
    await db_session.refresh(user)
    assert user.failed_login_attempts == settings.max_login_attempts
    assert user.lockout_until is not None
    assert user.lockout_until > datetime.now(UTC)

    # Next attempt should return 401 but with the lockout message
    response = await client.post(
        "/auth/login",
        data={"username": "lockoutuser", "password": TEST_PASSWORD},
    )
    assert response.status_code == 401
    assert "temporarily locked" in response.json()["detail"]

    # Successful login after lockout expires
    with patch(
        "ai_trading_discipline_copilot.services.auth_service.datetime"
    ) as mock_dt:
        # Mock UTC time to be after lockout duration
        future_time = datetime.now(UTC) + timedelta(
            minutes=settings.lockout_duration_minutes + 1
        )
        mock_dt.now.return_value = future_time
        # Mock UTC constant too if referenced
        mock_dt.UTC = UTC

        # Login should now succeed because lockout expired
        response = await client.post(
            "/auth/login",
            data={"username": "lockoutuser", "password": TEST_PASSWORD},
        )
        assert response.status_code == 200

        # Verify DB states are reset
        await db_session.refresh(user)
        assert user.failed_login_attempts == 0
        assert user.lockout_until is None


@pytest.mark.anyio
async def test_rate_limiting_on_login(client: AsyncClient) -> None:
    """Test that login requests are rate limited when enable_login_rate_limiting is True."""
    from ai_trading_discipline_copilot.core.limiter import limiter

    # Temporarily enable the limiter and ensure login rate limiting is True
    limiter.enabled = True
    get_settings().enable_login_rate_limiting = True
    try:
        # Send 11 login requests (limit is 10/minute)
        for idx in range(11):
            response = await client.post(
                "/auth/login",
                data={"username": "someuser", "password": TEST_PASSWORD},
            )
            if idx == 10:
                assert response.status_code == 429
                assert "Rate limit exceeded" in response.text
            else:
                # Prior requests should be invalid credentials (401)
                assert response.status_code == 401
    finally:
        # Restore disabled limiter state
        limiter.enabled = False


@pytest.mark.anyio
async def test_configurable_login_rate_limiting_bypass(client: AsyncClient) -> None:
    """Test that login rate limiting can be bypassed when enable_login_rate_limiting is False."""
    from ai_trading_discipline_copilot.core.limiter import limiter

    limiter.enabled = True
    get_settings().enable_login_rate_limiting = False
    try:
        # Send 12 login requests; all 12 should bypass rate limiting (status 401, not 429)
        for _ in range(12):
            response = await client.post(
                "/auth/login",
                data={"username": "someuser", "password": TEST_PASSWORD},
            )
            assert response.status_code == 401
    finally:
        limiter.enabled = False
        get_settings().enable_login_rate_limiting = True
