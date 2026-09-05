import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_trading_discipline_copilot.core.config import get_settings
from ai_trading_discipline_copilot.models.user import User

settings = get_settings()


@pytest.fixture(autouse=True)
def setup_oauth_config() -> None:
    """Ensure Google OAuth2 config settings are populated for tests."""
    settings.google_client_id = "test-client-id"
    settings.google_client_secret = SecretStr("test-client-secret")


@pytest.mark.anyio
async def test_google_login_redirect(client: AsyncClient) -> None:
    """Test that the login route redirects to Google's consent screen."""
    response = await client.get("/auth/oauth2/google/login", follow_redirects=False)
    assert response.status_code == 307

    location = response.headers["Location"]
    assert "https://accounts.google.com/o/oauth2/v2/auth" in location
    assert f"client_id={settings.google_client_id}" in location
    assert "scope=openid%20email%20profile" in location
    assert "state=" in location

    # Verify client cookie binding
    assert "oauth_state" in response.cookies
    assert response.cookies["oauth_state"] != ""


@pytest.mark.anyio
async def test_google_callback_register_new_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test Google callback creates a new verified user if they do not exist."""
    # Generate a valid signed state token
    state_payload = {
        "timestamp": datetime.now(UTC).timestamp(),
        "nonce": uuid.uuid4().hex,
    }
    state_token = jwt.encode(
        state_payload,
        settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm,
    )

    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {
        "access_token": "google-access-token",
        "id_token": "google-id-token",
    }

    mock_userinfo_resp = MagicMock()
    mock_userinfo_resp.status_code = 200
    mock_userinfo_resp.json.return_value = {
        "sub": "google-id-123",
        "email": "newuser@example.com",
        "email_verified": True,
        "name": "New User",
    }

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post.return_value = mock_token_resp
    mock_client.get.return_value = mock_userinfo_resp

    with patch(
        "ai_trading_discipline_copilot.routers.auth.httpx.AsyncClient",
        return_value=mock_client,
    ):
        client.cookies.set(
            "oauth_state", state_token, domain="testserver.local", path="/auth"
        )
        response = await client.get(
            "/auth/oauth2/google/callback",
            params={"code": "auth-code", "state": state_token},
            follow_redirects=False,
        )

        assert response.status_code == 307
        assert "#token=" in response.headers["Location"]
        assert "refresh_token" in response.cookies

        # Verify user was created in the DB as verified and linked to Google
        result = await db_session.execute(
            select(User).where(User.email == "newuser@example.com")
        )
        user = result.scalar_one_or_none()
        assert user is not None
        assert user.google_id == "google-id-123"
        assert user.is_verified is True
        assert user.hashed_password is None


@pytest.mark.anyio
async def test_google_callback_link_existing_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test Google callback links the google_id to an existing user email."""
    # Pre-add local user (unverified and without google_id linked)
    existing_user = User(
        username="existing",
        email="existing@example.com",
        hashed_password="somepasswordhash",  # noqa: S106
        is_verified=False,
    )
    db_session.add(existing_user)
    await db_session.commit()

    state_payload = {
        "timestamp": datetime.now(UTC).timestamp(),
        "nonce": uuid.uuid4().hex,
    }
    state_token = jwt.encode(
        state_payload,
        settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm,
    )

    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {"access_token": "google-access-token"}

    mock_userinfo_resp = MagicMock()
    mock_userinfo_resp.status_code = 200
    mock_userinfo_resp.json.return_value = {
        "sub": "google-id-456",
        "email": "existing@example.com",
        "email_verified": True,
    }

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post.return_value = mock_token_resp
    mock_client.get.return_value = mock_userinfo_resp

    with patch(
        "ai_trading_discipline_copilot.routers.auth.httpx.AsyncClient",
        return_value=mock_client,
    ):
        client.cookies.set(
            "oauth_state", state_token, domain="testserver.local", path="/auth"
        )
        response = await client.get(
            "/auth/oauth2/google/callback",
            params={"code": "auth-code", "state": state_token},
            follow_redirects=False,
        )

        assert response.status_code == 307
        assert "#token=" in response.headers["Location"]
        assert "refresh_token" in response.cookies

        # Verify Google ID was linked and user was verified
        await db_session.refresh(existing_user)
        assert existing_user.google_id == "google-id-456"
        assert existing_user.is_verified is True


@pytest.mark.anyio
async def test_google_callback_invalid_state(client: AsyncClient) -> None:
    """Test Google callback fails if state token is invalid."""
    client.cookies.set(
        "oauth_state", "invalid-state-token", domain="testserver.local", path="/auth"
    )
    response = await client.get(
        "/auth/oauth2/google/callback",
        params={"code": "auth-code", "state": "invalid-state-token"},
        follow_redirects=False,
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid OAuth state token"


@pytest.mark.anyio
async def test_google_callback_expired_state(client: AsyncClient) -> None:
    """Test Google callback fails if state token has expired."""
    state_payload = {
        # Expired (older than 10 minutes)
        "timestamp": datetime.now(UTC).timestamp() - 601,
        "nonce": uuid.uuid4().hex,
    }
    state_token = jwt.encode(
        state_payload,
        settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm,
    )

    client.cookies.set(
        "oauth_state", state_token, domain="testserver.local", path="/auth"
    )
    response = await client.get(
        "/auth/oauth2/google/callback",
        params={"code": "auth-code", "state": state_token},
        follow_redirects=False,
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "OAuth state token has expired"


@pytest.mark.anyio
async def test_google_callback_inactive_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test Google callback fails if the matching user is inactive."""
    # Pre-add inactive user
    inactive_user = User(
        username="inactive",
        email="inactive@example.com",
        hashed_password="somepasswordhash",  # noqa: S106
        is_verified=True,
        is_active=False,
    )
    db_session.add(inactive_user)
    await db_session.commit()

    state_payload = {
        "timestamp": datetime.now(UTC).timestamp(),
        "nonce": uuid.uuid4().hex,
    }
    state_token = jwt.encode(
        state_payload,
        settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm,
    )

    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {"access_token": "google-access-token"}

    mock_userinfo_resp = MagicMock()
    mock_userinfo_resp.status_code = 200
    mock_userinfo_resp.json.return_value = {
        "sub": "google-id-inactive",
        "email": "inactive@example.com",
        "email_verified": True,
    }

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post.return_value = mock_token_resp
    mock_client.get.return_value = mock_userinfo_resp

    with patch(
        "ai_trading_discipline_copilot.routers.auth.httpx.AsyncClient",
        return_value=mock_client,
    ):
        client.cookies.set(
            "oauth_state", state_token, domain="testserver.local", path="/auth"
        )
        response = await client.get(
            "/auth/oauth2/google/callback",
            params={"code": "auth-code", "state": state_token},
            follow_redirects=False,
        )

        assert response.status_code == 403
        assert response.json()["detail"] == "User account is disabled"

        # Verify database is not mutated (google_id remains unset)
        await db_session.refresh(inactive_user)
        assert inactive_user.google_id is None


@pytest.mark.anyio
async def test_google_callback_resets_lockout(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test Google callback resets failed login attempts and lockout."""
    # Pre-add locked user
    locked_user = User(
        username="lockedout",
        email="lockedout@example.com",
        hashed_password="somepasswordhash",  # noqa: S106
        is_verified=True,
        failed_login_attempts=5,
        lockout_until=datetime.now(UTC) + timedelta(minutes=15),
    )
    db_session.add(locked_user)
    await db_session.commit()

    state_payload = {
        "timestamp": datetime.now(UTC).timestamp(),
        "nonce": uuid.uuid4().hex,
    }
    state_token = jwt.encode(
        state_payload,
        settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm,
    )

    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {"access_token": "google-access-token"}

    mock_userinfo_resp = MagicMock()
    mock_userinfo_resp.status_code = 200
    mock_userinfo_resp.json.return_value = {
        "sub": "google-id-locked",
        "email": "lockedout@example.com",
        "email_verified": True,
    }

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post.return_value = mock_token_resp
    mock_client.get.return_value = mock_userinfo_resp

    with patch(
        "ai_trading_discipline_copilot.routers.auth.httpx.AsyncClient",
        return_value=mock_client,
    ):
        client.cookies.set(
            "oauth_state", state_token, domain="testserver.local", path="/auth"
        )
        response = await client.get(
            "/auth/oauth2/google/callback",
            params={"code": "auth-code", "state": state_token},
            follow_redirects=False,
        )

        assert response.status_code == 307
        await db_session.refresh(locked_user)
        assert locked_user.failed_login_attempts == 0
        assert locked_user.lockout_until is None


@pytest.mark.anyio
async def test_google_login_unconfigured(client: AsyncClient) -> None:
    """Test Google login fails with 500 if not configured."""
    with patch.object(settings, "google_client_id", None):
        response = await client.get("/auth/oauth2/google/login", follow_redirects=False)
        assert response.status_code == 500
        assert "not configured" in response.json()["detail"]


@pytest.mark.anyio
async def test_google_callback_unconfigured(client: AsyncClient) -> None:
    """Test Google callback fails with 500 if client secret is not configured."""
    with patch.object(settings, "google_client_secret", None):
        response = await client.get(
            "/auth/oauth2/google/callback",
            params={"code": "auth-code", "state": "state"},
            follow_redirects=False,
        )
        assert response.status_code == 500
        assert "not configured" in response.json()["detail"]


@pytest.mark.anyio
async def test_google_callback_token_exchange_failure(client: AsyncClient) -> None:
    """Test Google callback fails if Google token endpoint returns error."""
    state_payload = {
        "timestamp": datetime.now(UTC).timestamp(),
        "nonce": uuid.uuid4().hex,
    }
    state_token = jwt.encode(
        state_payload,
        settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm,
    )

    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 400
    mock_token_resp.text = "Bad Request"

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post.return_value = mock_token_resp

    with patch(
        "ai_trading_discipline_copilot.routers.auth.httpx.AsyncClient",
        return_value=mock_client,
    ):
        client.cookies.set(
            "oauth_state", state_token, domain="testserver.local", path="/auth"
        )
        response = await client.get(
            "/auth/oauth2/google/callback",
            params={"code": "auth-code", "state": state_token},
            follow_redirects=False,
        )

        assert response.status_code == 401
        assert "exchange" in response.json()["detail"]


@pytest.mark.anyio
async def test_google_callback_userinfo_failure(client: AsyncClient) -> None:
    """Test Google callback fails if Google userinfo endpoint returns error."""
    state_payload = {
        "timestamp": datetime.now(UTC).timestamp(),
        "nonce": uuid.uuid4().hex,
    }
    state_token = jwt.encode(
        state_payload,
        settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm,
    )

    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {"access_token": "token"}

    mock_userinfo_resp = MagicMock()
    mock_userinfo_resp.status_code = 400
    mock_userinfo_resp.text = "Error"

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post.return_value = mock_token_resp
    mock_client.get.return_value = mock_userinfo_resp

    with patch(
        "ai_trading_discipline_copilot.routers.auth.httpx.AsyncClient",
        return_value=mock_client,
    ):
        client.cookies.set(
            "oauth_state", state_token, domain="testserver.local", path="/auth"
        )
        response = await client.get(
            "/auth/oauth2/google/callback",
            params={"code": "auth-code", "state": state_token},
            follow_redirects=False,
        )

        assert response.status_code == 401
        assert "profile" in response.json()["detail"]


@pytest.mark.anyio
async def test_google_callback_incomplete_profile(client: AsyncClient) -> None:
    """Test Google callback fails if Google userinfo profile is incomplete."""
    state_payload = {
        "timestamp": datetime.now(UTC).timestamp(),
        "nonce": uuid.uuid4().hex,
    }
    state_token = jwt.encode(
        state_payload,
        settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm,
    )

    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {"access_token": "token"}

    mock_userinfo_resp = MagicMock()
    mock_userinfo_resp.status_code = 200
    mock_userinfo_resp.json.return_value = {
        # missing sub and email
        "name": "incomplete"
    }

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post.return_value = mock_token_resp
    mock_client.get.return_value = mock_userinfo_resp

    with patch(
        "ai_trading_discipline_copilot.routers.auth.httpx.AsyncClient",
        return_value=mock_client,
    ):
        client.cookies.set(
            "oauth_state", state_token, domain="testserver.local", path="/auth"
        )
        response = await client.get(
            "/auth/oauth2/google/callback",
            params={"code": "auth-code", "state": state_token},
            follow_redirects=False,
        )

        assert response.status_code == 401
        assert "incomplete" in response.json()["detail"]


@pytest.mark.anyio
async def test_google_callback_unverified_email(client: AsyncClient) -> None:
    """Test Google callback fails if Google profile email is not verified."""
    state_payload = {
        "timestamp": datetime.now(UTC).timestamp(),
        "nonce": uuid.uuid4().hex,
    }
    state_token = jwt.encode(
        state_payload,
        settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm,
    )

    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {"access_token": "token"}

    mock_userinfo_resp = MagicMock()
    mock_userinfo_resp.status_code = 200
    mock_userinfo_resp.json.return_value = {
        "sub": "google-id-unverified",
        "email": "unverified@example.com",
        "email_verified": False,  # Unverified!
    }

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post.return_value = mock_token_resp
    mock_client.get.return_value = mock_userinfo_resp

    with patch(
        "ai_trading_discipline_copilot.routers.auth.httpx.AsyncClient",
        return_value=mock_client,
    ):
        client.cookies.set(
            "oauth_state", state_token, domain="testserver.local", path="/auth"
        )
        response = await client.get(
            "/auth/oauth2/google/callback",
            params={"code": "auth-code", "state": state_token},
            follow_redirects=False,
        )

        assert response.status_code == 401
        assert "verified" in response.json()["detail"]


@pytest.mark.anyio
async def test_google_callback_empty_derived_username(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test Google callback registers user with google_user fallback
    if the email results in an empty base username.
    """
    state_payload = {
        "timestamp": datetime.now(UTC).timestamp(),
        "nonce": uuid.uuid4().hex,
    }
    state_token = jwt.encode(
        state_payload,
        settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm,
    )

    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {"access_token": "token"}

    mock_userinfo_resp = MagicMock()
    mock_userinfo_resp.status_code = 200
    mock_userinfo_resp.json.return_value = {
        "sub": "google-id-empty-username",
        "email": "!!!@example.com",  # No alphanumeric/underscore characters
        "email_verified": True,
    }

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post.return_value = mock_token_resp
    mock_client.get.return_value = mock_userinfo_resp

    with patch(
        "ai_trading_discipline_copilot.routers.auth.httpx.AsyncClient",
        return_value=mock_client,
    ):
        client.cookies.set(
            "oauth_state", state_token, domain="testserver.local", path="/auth"
        )
        response = await client.get(
            "/auth/oauth2/google/callback",
            params={"code": "auth-code", "state": state_token},
            follow_redirects=False,
        )

        assert response.status_code == 307
        result = await db_session.execute(
            select(User).where(User.email == "!!!@example.com")
        )
        user = result.scalar_one_or_none()
        assert user is not None
        assert user.username == "google_user"


@pytest.mark.anyio
async def test_google_callback_client_binding_mismatch(client: AsyncClient) -> None:
    """Test callback fails if state token does not match the client's cookie."""
    state_payload = {
        "timestamp": datetime.now(UTC).timestamp(),
        "nonce": uuid.uuid4().hex,
    }
    state_token = jwt.encode(
        state_payload,
        settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm,
    )

    # State issued for client A is rejected by client B (different or no cookie)
    client.cookies.set(
        "oauth_state", "different-state-token", domain="testserver.local", path="/auth"
    )
    response = await client.get(
        "/auth/oauth2/google/callback",
        params={"code": "auth-code", "state": state_token},
        follow_redirects=False,
    )
    assert response.status_code == 401
    assert "mismatch or missing binding" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_google_callback_replay_prevention(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test that a successfully accepted OAuth state cannot be replayed."""
    state_payload = {
        "timestamp": datetime.now(UTC).timestamp(),
        "nonce": uuid.uuid4().hex,
    }
    state_token = jwt.encode(
        state_payload,
        settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm,
    )

    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {
        "access_token": "google-access-token",
        "id_token": "google-id-token",
    }

    mock_userinfo_resp = MagicMock()
    mock_userinfo_resp.status_code = 200
    mock_userinfo_resp.json.return_value = {
        "sub": "google-id-replay",
        "email": "replayuser@example.com",
        "email_verified": True,
        "name": "Replay User",
    }

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post.return_value = mock_token_resp
    mock_client.get.return_value = mock_userinfo_resp

    with patch(
        "ai_trading_discipline_copilot.routers.auth.httpx.AsyncClient",
        return_value=mock_client,
    ):
        # 1. First request - cookie is set and matches
        client.cookies.set(
            "oauth_state", state_token, domain="testserver.local", path="/auth"
        )
        response1 = await client.get(
            "/auth/oauth2/google/callback",
            params={"code": "auth-code", "state": state_token},
            follow_redirects=False,
        )
        assert response1.status_code == 307

        # Verify the oauth_state cookie was deleted (consumed)
        assert "oauth_state" not in client.cookies

        # 2. Second request (replay attempt) - cookie has been consumed/deleted
        response2 = await client.get(
            "/auth/oauth2/google/callback",
            params={"code": "auth-code", "state": state_token},
            follow_redirects=False,
        )
        assert response2.status_code == 401
        assert "mismatch or missing binding" in response2.json()["detail"].lower()
