import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ai_trading_discipline_copilot.core.config import get_settings
from ai_trading_discipline_copilot.core.security import (
    _create_token,
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_refresh_token,
)
from ai_trading_discipline_copilot.models.email_verification_token import (
    EmailVerificationToken,
)
from ai_trading_discipline_copilot.models.password_reset_token import (
    PasswordResetToken,
)
from ai_trading_discipline_copilot.models.refresh_token import RefreshToken
from ai_trading_discipline_copilot.models.user import User
from ai_trading_discipline_copilot.services.email_verification_service import (
    EmailVerificationService,
)
from ai_trading_discipline_copilot.services.password_reset_service import (
    PasswordResetService,
)

settings = get_settings()
TEST_PASSWORD = "StrongPass1!"  # noqa: S105
NEW_TEST_PASSWORD = "NewPassword2?"  # noqa: S105


# ──────────────────────────────────────────────────────────────────────
# 1. Authentication - Login
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_login_locked_account(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test that login fails when the user account is locked."""
    # Arrange
    user = User(
        username="lockeduser",
        email="locked@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
        is_verified=True,
        lockout_until=datetime.now(UTC) + timedelta(minutes=15),
        failed_login_attempts=10,
    )
    db_session.add(user)
    await db_session.commit()

    # Act
    response = await client.post(
        "/auth/login",
        data={"username": "lockeduser", "password": TEST_PASSWORD},
    )

    # Assert
    assert response.status_code == 401
    assert "locked" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_login_lockout_duration_expired_resets_attempts(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test that an expired lockout allows successful login and resets failures."""
    # Arrange
    user = User(
        username="expiredlock",
        email="explock@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
        is_verified=True,
        lockout_until=datetime.now(UTC) - timedelta(minutes=1),
        failed_login_attempts=10,
    )
    db_session.add(user)
    await db_session.commit()

    # Act
    response = await client.post(
        "/auth/login",
        data={"username": "expiredlock", "password": TEST_PASSWORD},
    )

    # Assert
    assert response.status_code == 200
    await db_session.refresh(user)
    assert user.failed_login_attempts == 0
    assert user.lockout_until is None


@pytest.mark.anyio
async def test_login_consecutive_failed_attempts_lockout(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test that reaching max failed attempts locks the user account."""
    # Arrange
    user = User(
        username="lockouttrigger",
        email="trigger@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
        is_verified=True,
        failed_login_attempts=settings.max_login_attempts - 1,
    )
    db_session.add(user)
    await db_session.commit()

    # Act
    response = await client.post(
        "/auth/login",
        data={"username": "lockouttrigger", "password": "wrongpassword"},
    )

    # Assert
    assert response.status_code == 401
    db_session.expire_all()
    result = await db_session.execute(
        select(User).where(User.username == "lockouttrigger")
    )
    updated_user = result.scalar_one()
    assert updated_user.failed_login_attempts == settings.max_login_attempts
    assert updated_user.lockout_until is not None
    assert updated_user.lockout_until > datetime.now(UTC)


@pytest.mark.anyio
async def test_login_cookie_attributes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test that login sets the HttpOnly refresh token cookie with security attributes."""
    # Arrange
    user = User(
        username="cookieuser",
        email="cookie@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()

    # Act
    response = await client.post(
        "/auth/login",
        data={"username": "cookieuser", "password": TEST_PASSWORD},
    )

    # Assert
    assert response.status_code == 200
    cookie = response.headers.get("set-cookie")
    assert cookie is not None
    assert "HttpOnly" in cookie
    assert "Path=/auth" in cookie
    if settings.cookie_secure:
        assert "Secure" in cookie
    assert f"samesite={settings.cookie_samesite.lower()}" in cookie.lower()


# ──────────────────────────────────────────────────────────────────────
# 2. Refresh Token Lifecycle
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_refresh_expired_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test that refreshing with an expired token fails."""
    # Arrange
    user = User(
        username="refexpired",
        email="refexpired@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()

    token, jti = _create_token(str(user.id), timedelta(minutes=-10), "refresh")

    session = RefreshToken(
        user_id=user.id,
        token_hash=hash_refresh_token(token),
        jti=jti,
        expires_at=datetime.now(UTC) - timedelta(minutes=10),
    )
    db_session.add(session)
    await db_session.commit()

    client.cookies.set("refresh_token", token)

    # Act
    response = await client.post("/auth/refresh")

    # Assert
    assert response.status_code == 401
    assert "invalid" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_refresh_revoked_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test that refreshing with a revoked token fails."""
    # Arrange
    user = User(
        username="refrevoked",
        email="refrevoked@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()

    token, jti = create_refresh_token(str(user.id))
    session = RefreshToken(
        user_id=user.id,
        token_hash=hash_refresh_token(token),
        jti=jti,
        revoked_at=datetime.now(UTC),
    )
    db_session.add(session)
    await db_session.commit()

    client.cookies.set("refresh_token", token)

    # Act
    response = await client.post("/auth/refresh")

    # Assert
    assert response.status_code == 401
    assert "revoked" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_refresh_malformed_token(client: AsyncClient) -> None:
    """Test that refreshing with a malformed token fails."""
    # Arrange
    client.cookies.set("refresh_token", "not.a.valid.jwt.payload")

    # Act
    response = await client.post("/auth/refresh")

    # Assert
    assert response.status_code == 401
    assert "invalid" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_refresh_invalid_signature(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test that refreshing with a tampered signature fails."""
    # Arrange
    user = User(
        username="refbadsig",
        email="refbadsig@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()

    token, jti = create_refresh_token(str(user.id))
    tampered_token = token[:-4] + "aaaa"

    session = RefreshToken(
        user_id=user.id,
        token_hash=hash_refresh_token(token),
        jti=jti,
    )
    db_session.add(session)
    await db_session.commit()

    client.cookies.set("refresh_token", tampered_token)

    # Act
    response = await client.post("/auth/refresh")

    # Assert
    assert response.status_code == 401
    assert "invalid" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_refresh_missing_cookie(client: AsyncClient) -> None:
    """Test that refreshing with a missing cookie fails."""
    # Arrange
    client.cookies.clear()

    # Act
    response = await client.post("/auth/refresh")

    # Assert
    assert response.status_code == 401
    assert "missing" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_refresh_multiple_sequential_refreshes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test sequential token rotations successfully generate unique new cookies."""
    # Arrange
    user = User(
        username="seqrefresh",
        email="seq@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()

    # Login to get initial refresh token
    login_res = await client.post(
        "/auth/login",
        data={"username": "seqrefresh", "password": TEST_PASSWORD},
    )
    assert login_res.status_code == 200
    token1 = login_res.cookies["refresh_token"]

    # Refresh 1
    client.cookies.set("refresh_token", token1)
    res1 = await client.post("/auth/refresh")
    assert res1.status_code == 200
    token2 = res1.cookies["refresh_token"]

    # Refresh 2
    client.cookies.set("refresh_token", token2)
    res2 = await client.post("/auth/refresh")
    assert res2.status_code == 200
    token3 = res2.cookies["refresh_token"]

    assert token1 != token2
    assert token2 != token3


@pytest.mark.anyio
async def test_refresh_token_reuse_compromise_handling(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test that refresh token reuse revokes all active sessions for security."""
    # Arrange
    user = User(
        username="reusecompromise",
        email="compromise@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()

    # Create session A
    res_a = await client.post(
        "/auth/login",
        data={"username": "reusecompromise", "password": TEST_PASSWORD},
    )
    token_a = res_a.cookies["refresh_token"]

    # Create session B
    res_b = await client.post(
        "/auth/login",
        data={"username": "reusecompromise", "password": TEST_PASSWORD},
    )
    assert res_b.status_code == 200

    # Rotate Session A
    client.cookies.set("refresh_token", token_a)
    rotate_res = await client.post("/auth/refresh")
    assert rotate_res.status_code == 200

    # Present Session A again (Reuse detection!)
    client.cookies.set("refresh_token", token_a)
    reuse_res = await client.post("/auth/refresh")
    assert reuse_res.status_code == 401
    assert "revoked" in reuse_res.json()["detail"].lower()

    # Verify BOTH session A and session B are revoked
    user_id = user.id
    db_session.expire_all()
    result = await db_session.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
        )
    )
    assert len(result.scalars().all()) == 0


# ──────────────────────────────────────────────────────────────────────
# 3. Logout
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_logout_twice_remains_safe(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test that sequential logout calls behave idempotently and remain safe."""
    # Arrange
    user = User(
        username="logouttwice",
        email="twice@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()

    login_res = await client.post(
        "/auth/login",
        data={"username": "logouttwice", "password": TEST_PASSWORD},
    )
    token = login_res.cookies["refresh_token"]

    # Logout 1
    client.cookies.set("refresh_token", token)
    logout_res = await client.post("/auth/logout")
    assert logout_res.status_code == 204

    # Logout 2 (already revoked token)
    client.cookies.set("refresh_token", token)
    logout_res2 = await client.post("/auth/logout")
    assert logout_res2.status_code == 204


@pytest.mark.anyio
async def test_logout_revoked_token_cannot_refresh(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test that logged-out refresh token cannot be used to refresh session."""
    # Arrange
    user = User(
        username="logoutcantref",
        email="cantref@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()

    login_res = await client.post(
        "/auth/login",
        data={"username": "logoutcantref", "password": TEST_PASSWORD},
    )
    token = login_res.cookies["refresh_token"]

    # Logout
    client.cookies.set("refresh_token", token)
    await client.post("/auth/logout")

    # Try to refresh
    client.cookies.set("refresh_token", token)
    refresh_res = await client.post("/auth/refresh")
    assert refresh_res.status_code == 401


# ──────────────────────────────────────────────────────────────────────
# 4. Registration
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_register_missing_required_fields(client: AsyncClient) -> None:
    """Test that registration fails when missing required fields."""
    # Arrange: payload missing password
    payload = {
        "username": "missingfields",
        "email": "missing@example.com",
    }

    # Act
    response = await client.post("/auth/register", json=payload)

    # Assert
    assert response.status_code == 422


@pytest.mark.anyio
async def test_register_invalid_email_format(client: AsyncClient) -> None:
    """Test that registration fails when email format is invalid."""
    # Arrange
    payload = {
        "username": "bademail",
        "email": "not-an-email",
        "password": TEST_PASSWORD,
    }

    # Act
    response = await client.post("/auth/register", json=payload)

    # Assert
    assert response.status_code == 422


@pytest.mark.anyio
async def test_register_invalid_password(client: AsyncClient) -> None:
    """Test that registration fails with weak password."""
    # Arrange
    payload = {
        "username": "badpass",
        "email": "badpass@example.com",
        "password": "123",
    }

    # Act
    response = await client.post("/auth/register", json=payload)

    # Assert
    assert response.status_code == 422


@pytest.mark.anyio
async def test_register_password_hashing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test that registered user passwords are securely hashed in the database."""
    # Arrange
    payload = {
        "username": "hashcheck",
        "email": "hash@example.com",
        "password": TEST_PASSWORD,
    }

    # Act
    response = await client.post("/auth/register", json=payload)
    assert response.status_code == 201

    # Assert password in database is NOT plaintext and starts with $2b$ (bcrypt hash)
    result = await db_session.execute(select(User).where(User.username == "hashcheck"))
    user = result.scalar_one()
    assert user.hashed_password is not None
    assert user.hashed_password != TEST_PASSWORD
    assert user.hashed_password.startswith("$2b$")

    # Mark user as verified so they can log in
    user.is_verified = True
    await db_session.commit()

    # Attempt login through production authentication flow to verify the password check works
    login_res = await client.post(
        "/auth/login",
        data={"username": "hashcheck", "password": TEST_PASSWORD},
    )
    assert login_res.status_code == 200


# ──────────────────────────────────────────────────────────────────────
# 5. Email Verification
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_email_verification_expired_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test that email verification fails if token is expired."""
    # Arrange
    user = User(
        username="verexpired",
        email="verexpired@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
        is_verified=False,
    )
    db_session.add(user)
    await db_session.commit()

    plain = await EmailVerificationService.create_verification_token(db_session, user)
    token_hash = EmailVerificationService.hash_token(plain)

    # Expire the token
    result = await db_session.execute(
        select(EmailVerificationToken).where(
            EmailVerificationToken.token_hash == token_hash
        )
    )
    db_token = result.scalar_one()
    db_token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    # Act
    response = await client.post("/auth/verify-email", json={"token": plain})

    # Assert
    assert response.status_code == 401
    assert "invalid or expired" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_email_verification_already_verified(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test verification behaves correctly for an already verified account."""
    # Arrange
    user = User(
        username="alreadyver",
        email="already@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()

    plain = await EmailVerificationService.create_verification_token(db_session, user)

    # Act
    response = await client.post("/auth/verify-email", json={"token": plain})

    # Assert
    assert response.status_code == 200
    assert response.json()["message"] == "Email verified successfully."


@pytest.mark.anyio
async def test_email_verification_invalid_token(client: AsyncClient) -> None:
    """Test verification fails with invalid token."""
    # Act
    response = await client.post(
        "/auth/verify-email", json={"token": "notarealtoken123"}
    )

    # Assert
    assert response.status_code == 401


@pytest.mark.anyio
async def test_email_verification_reused_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test that a verification token cannot be reused."""
    # Arrange
    user = User(
        username="reusedver",
        email="reusedver@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
        is_verified=False,
    )
    db_session.add(user)
    await db_session.commit()

    plain = await EmailVerificationService.create_verification_token(db_session, user)

    # Act 1
    res1 = await client.post("/auth/verify-email", json={"token": plain})
    assert res1.status_code == 200

    # Act 2 (Re-use verification token)
    res2 = await client.post("/auth/verify-email", json={"token": plain})
    assert res2.status_code == 401


# ──────────────────────────────────────────────────────────────────────
# 6. Password Reset
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_password_reset_invalid_token(client: AsyncClient) -> None:
    """Test password reset fails with invalid token."""
    # Act
    response = await client.post(
        "/auth/reset-password",
        json={"token": "invalidtoken" * 3, "new_password": NEW_TEST_PASSWORD},
    )

    # Assert
    assert response.status_code == 401


@pytest.mark.anyio
async def test_password_reset_expired_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test password reset fails with expired token."""
    # Arrange
    user = User(
        username="resetexpired",
        email="resetexp@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()

    plain = await PasswordResetService.create_reset_token(db_session, user)
    token_hash = PasswordResetService.hash_token(plain)

    # Expire reset token
    result = await db_session.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    db_token = result.scalar_one()
    db_token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    # Act
    response = await client.post(
        "/auth/reset-password",
        json={"token": plain, "new_password": NEW_TEST_PASSWORD},
    )

    # Assert
    assert response.status_code == 401


@pytest.mark.anyio
async def test_password_reset_reused_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test that a password reset token cannot be reused."""
    # Arrange
    user = User(
        username="resetreused",
        email="resetre@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()

    plain = await PasswordResetService.create_reset_token(db_session, user)

    # Reset 1
    res1 = await client.post(
        "/auth/reset-password",
        json={"token": plain, "new_password": NEW_TEST_PASSWORD},
    )
    assert res1.status_code == 200

    # Act 2 (Re-use password reset token)
    res2 = await client.post(
        "/auth/reset-password",
        json={"token": plain, "new_password": "EvenNewerPassword3!"},
    )
    assert res2.status_code == 401


@pytest.mark.anyio
async def test_password_reset_login_flow(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test full reset flow: login fails with old password, succeeds with new."""
    # Arrange
    user = User(
        username="resetflow",
        email="resetflow@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()

    plain = await PasswordResetService.create_reset_token(db_session, user)

    # Reset password
    await client.post(
        "/auth/reset-password",
        json={"token": plain, "new_password": NEW_TEST_PASSWORD},
    )

    # Login fails using old password
    login_old = await client.post(
        "/auth/login",
        data={"username": "resetflow", "password": TEST_PASSWORD},
    )
    assert login_old.status_code == 401

    # Login succeeds using new password
    login_new = await client.post(
        "/auth/login",
        data={"username": "resetflow", "password": NEW_TEST_PASSWORD},
    )
    assert login_new.status_code == 200


# ──────────────────────────────────────────────────────────────────────
# 7. Google OAuth
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_google_oauth_inactive_account(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test Google callback fails if account associated with ID/email is inactive."""
    # Arrange: state token
    state_payload = {
        "timestamp": datetime.now(UTC).timestamp(),
        "nonce": uuid.uuid4().hex,
    }
    state_token = jwt.encode(
        state_payload,
        settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm,
    )

    # Inactive user
    user = User(
        username="googleinactive",
        email="inactive@google.com",
        hashed_password=None,
        google_id="g123",
        is_active=False,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()

    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {
        "access_token": "google-access-token",
        "id_token": "google-id-token",
    }

    mock_userinfo_resp = MagicMock()
    mock_userinfo_resp.status_code = 200
    mock_userinfo_resp.json.return_value = {
        "sub": "g123",
        "email": "inactive@google.com",
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

        # Act
        response = await client.get(
            "/auth/oauth2/google/callback",
            params={"code": "auth-code", "state": state_token},
            follow_redirects=False,
        )

        # Assert: Forbidden
        assert response.status_code == 403
        assert "disabled" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_google_oauth_invalid_token_callback(client: AsyncClient) -> None:
    """Test Google callback fails gracefully when token exchange fails."""
    # Arrange
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
    mock_token_resp.text = "invalid_grant"

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

        # Act
        response = await client.get(
            "/auth/oauth2/google/callback",
            params={"code": "invalid-code", "state": state_token},
            follow_redirects=False,
        )

        # Assert
        assert response.status_code == 401
        assert "failed to exchange" in response.json()["detail"].lower()


# ──────────────────────────────────────────────────────────────────────
# 8. Authorization
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_auth_protected_endpoints_missing_jwt(
    client: AsyncClient,
) -> None:
    """Test that requesting protected route without authorization returns 401."""
    # Act
    response = await client.get("/auth/me")
    # Assert
    assert response.status_code == 401
    assert "not authenticated" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_auth_protected_endpoints_expired_jwt(
    client: AsyncClient,
) -> None:
    """Test that requesting protected route with expired JWT returns 401."""
    # Arrange
    token, _ = _create_token(str(uuid.uuid4()), timedelta(minutes=-10), "access")
    client.headers["Authorization"] = f"Bearer {token}"

    # Act
    response = await client.get("/auth/me")

    # Assert
    assert response.status_code == 401
    assert "could not validate credentials" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_auth_protected_endpoints_malformed_jwt(
    client: AsyncClient,
) -> None:
    """Test that requesting protected route with malformed JWT returns 401."""
    # Arrange
    client.headers["Authorization"] = "Bearer not-a-valid-token"

    # Act
    response = await client.get("/auth/me")

    # Assert
    assert response.status_code == 401


@pytest.mark.anyio
async def test_auth_protected_endpoints_invalid_signature(
    client: AsyncClient,
) -> None:
    """Test that requesting protected route with bad signature JWT returns 401."""
    # Arrange
    token, _ = create_access_token(str(uuid.uuid4()))
    tampered_token = token[:-4] + "aaaa"
    client.headers["Authorization"] = f"Bearer {tampered_token}"

    # Act
    response = await client.get("/auth/me")

    # Assert
    assert response.status_code == 401


@pytest.mark.anyio
async def test_auth_protected_endpoints_tampered_jwt(
    client: AsyncClient,
) -> None:
    """Test that requesting protected route with tampered claims signature returns 401."""
    # Arrange
    tampered_token = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access"},
        "wrong-secret-key-123",
        algorithm="HS256",
    )
    client.headers["Authorization"] = f"Bearer {tampered_token}"

    # Act
    response = await client.get("/auth/me")

    # Assert
    assert response.status_code == 401


# ──────────────────────────────────────────────────────────────────────
# 9. Session Management
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_session_revoke_current(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test that revoking current session cleans DB state and clears cookies."""
    # Arrange
    user = User(
        username="revokecurrent",
        email="current@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()

    login_res = await client.post(
        "https://testserver/auth/login",
        data={"username": "revokecurrent", "password": TEST_PASSWORD},
    )
    access_token = login_res.json()["access_token"]

    client.headers["Authorization"] = f"Bearer {access_token}"

    # Get sessions
    sess_res = await client.get("https://testserver/auth/sessions")
    assert sess_res.status_code == 200
    sessions = sess_res.json()
    assert len(sessions) == 1
    session_id = sessions[0]["id"]

    # Revoke session
    revoke_res = await client.delete(f"https://testserver/auth/sessions/{session_id}")
    assert revoke_res.status_code == 204

    # Verify session is marked revoked
    db_session.expire_all()
    result = await db_session.execute(
        select(RefreshToken).where(RefreshToken.id == uuid.UUID(session_id))
    )
    session_in_db = result.scalar_one()
    assert session_in_db.revoked_at is not None

    # Verify cookie deletion header was sent in response
    set_cookie = revoke_res.headers.get("set-cookie")
    assert set_cookie is not None
    assert "refresh_token" in set_cookie
    assert "max-age=0" in set_cookie.lower() or "expires=" in set_cookie.lower()


@pytest.mark.anyio
async def test_session_revoked_cannot_refresh(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test that a deleted/revoked session cannot be refreshed."""
    # Arrange
    user = User(
        username="revokedcantref",
        email="revokedcant@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()

    login_res = await client.post(
        "/auth/login",
        data={"username": "revokedcantref", "password": TEST_PASSWORD},
    )
    access_token = login_res.json()["access_token"]
    refresh_token = login_res.cookies["refresh_token"]

    client.headers["Authorization"] = f"Bearer {access_token}"
    client.cookies.set("refresh_token", refresh_token)

    # Get sessions
    sess_res = await client.get("/auth/sessions")
    session_id = sess_res.json()[0]["id"]

    # Revoke session
    await client.delete(f"/auth/sessions/{session_id}")

    # Act
    client.cookies.set("refresh_token", refresh_token)
    response = await client.post("/auth/refresh")

    # Assert
    assert response.status_code == 401


# ──────────────────────────────────────────────────────────────────────
# 10. Database Behaviour
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_db_transaction_rollback(db_session: AsyncSession) -> None:
    """Test database transaction rollback handles errors correctly."""
    # Arrange
    user = User(
        username="rollbackuser",
        email="rollback@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
        is_verified=True,
    )

    # Act
    try:
        async with db_session.begin_nested():
            db_session.add(user)
            raise ValueError("Triggering Rollback")
    except ValueError:
        pass

    # Assert
    result = await db_session.execute(
        select(User).where(User.username == "rollbackuser")
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.anyio
async def test_db_cascade_deletes(db_session: AsyncSession) -> None:
    """Test cascade delete propagates correctly across tables when user is deleted."""
    # Arrange
    user = User(
        username="cascadeuser",
        email="cascade@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
        is_verified=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    session = RefreshToken(
        user_id=user.id,
        token_hash="sessionhash123",  # noqa: S106
        jti="jti123",
    )
    email_tok = EmailVerificationToken(
        user_id=user.id,
        token_hash="emailhash123",  # noqa: S106
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    reset_tok = PasswordResetToken(
        user_id=user.id,
        token_hash="resethash123",  # noqa: S106
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    db_session.add_all([session, email_tok, reset_tok])
    await db_session.commit()

    # Act
    await db_session.delete(user)
    await db_session.commit()

    # Assert
    res_sess = await db_session.execute(
        select(RefreshToken).where(RefreshToken.user_id == user.id)
    )
    assert res_sess.scalar_one_or_none() is None

    res_email = await db_session.execute(
        select(EmailVerificationToken).where(EmailVerificationToken.user_id == user.id)
    )
    assert res_email.scalar_one_or_none() is None

    res_reset = await db_session.execute(
        select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
    )
    assert res_reset.scalar_one_or_none() is None


@pytest.mark.anyio
async def test_db_duplicate_constraint_handling(db_session: AsyncSession) -> None:
    """Test duplicate constraint database trigger is handled gracefully."""
    # Arrange
    user1 = User(
        username="duptrigger",
        email="duptrigger@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
        is_verified=True,
    )
    user2 = User(
        username="duptrigger",
        email="other@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
        is_verified=True,
    )

    db_session.add(user1)
    await db_session.commit()

    # Act & Assert
    db_session.add(user2)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
