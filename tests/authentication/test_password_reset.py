from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_trading_discipline_copilot.core.exceptions import UnauthorizedException
from ai_trading_discipline_copilot.core.security import hash_password, verify_password
from ai_trading_discipline_copilot.models.password_reset_token import PasswordResetToken
from ai_trading_discipline_copilot.models.refresh_token import RefreshToken
from ai_trading_discipline_copilot.models.user import User
from ai_trading_discipline_copilot.services.password_reset_service import (
    PasswordResetService,
)
from ai_trading_discipline_copilot.services.refresh_token_service import (
    RefreshTokenService,
)

TEST_PASSWORD = "OldPassword1!"  # noqa: S105
NEW_TEST_PASSWORD = "NewPassword2?"  # noqa: S105


@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create a test user in the database."""
    user = User(
        username="resetuser",
        email="resetuser@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.anyio
async def test_generate_and_hash_token() -> None:
    """Test generating a plain-text token and hashing it."""
    plain = PasswordResetService.generate_token()
    assert isinstance(plain, str)
    assert len(plain) >= 32

    hashed = PasswordResetService.hash_token(plain)
    assert isinstance(hashed, str)
    assert len(hashed) == 64  # SHA-256 hex digest is 64 chars


@pytest.mark.anyio
async def test_create_reset_token(
    db_session: AsyncSession,
    test_user: User,
) -> None:
    """Test creating a password reset token in the database."""
    plain_token = await PasswordResetService.create_reset_token(db_session, test_user)
    assert plain_token is not None

    token_hash = PasswordResetService.hash_token(plain_token)

    # Verify token is saved in DB
    result = await db_session.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    db_token = result.scalar_one_or_none()
    assert db_token is not None
    assert db_token.user_id == test_user.id
    assert db_token.used_at is None
    # Check expiration is roughly 15 minutes in future
    time_diff = db_token.expires_at - datetime.now(UTC)
    assert timedelta(minutes=14) < time_diff < timedelta(minutes=16)


@pytest.mark.anyio
async def test_create_reset_token_deletes_previous_unused(
    db_session: AsyncSession,
    test_user: User,
) -> None:
    """Test that creating a new token deletes any previous unused tokens for user."""
    # First token
    token_1 = await PasswordResetService.create_reset_token(db_session, test_user)
    hash_1 = PasswordResetService.hash_token(token_1)

    # Second token
    token_2 = await PasswordResetService.create_reset_token(db_session, test_user)
    hash_2 = PasswordResetService.hash_token(token_2)

    # First token should be deleted
    result_1 = await db_session.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_1)
    )
    assert result_1.scalar_one_or_none() is None

    # Second token should exist
    result_2 = await db_session.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_2)
    )
    assert result_2.scalar_one_or_none() is not None


@pytest.mark.anyio
async def test_create_reset_token_keeps_previous_used(
    db_session: AsyncSession,
    test_user: User,
) -> None:
    """Test that creating a new token does not delete previously used tokens."""
    token_1 = await PasswordResetService.create_reset_token(db_session, test_user)
    hash_1 = PasswordResetService.hash_token(token_1)

    # Mark first token as used
    result = await db_session.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_1)
    )
    db_token_1 = result.scalar_one()
    db_token_1.used_at = datetime.now(UTC)
    await db_session.commit()

    # Create new token
    token_2 = await PasswordResetService.create_reset_token(db_session, test_user)
    hash_2 = PasswordResetService.hash_token(token_2)

    # Both tokens should exist
    result_1 = await db_session.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_1)
    )
    assert result_1.scalar_one_or_none() is not None

    result_2 = await db_session.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_2)
    )
    assert result_2.scalar_one_or_none() is not None


@pytest.mark.anyio
async def test_validate_token_success(
    db_session: AsyncSession,
    test_user: User,
) -> None:
    """Test validating a valid token."""
    plain = await PasswordResetService.create_reset_token(db_session, test_user)
    db_token = await PasswordResetService.validate_token(db_session, plain)
    assert db_token is not None
    assert db_token.user.id == test_user.id


@pytest.mark.anyio
async def test_validate_token_not_found(
    db_session: AsyncSession,
) -> None:
    """Test validation fails for non-existent token."""
    with pytest.raises(UnauthorizedException) as exc_info:
        await PasswordResetService.validate_token(db_session, "nonexistenttoken" * 3)
    assert exc_info.value.detail == "Invalid or expired password reset token"


@pytest.mark.anyio
async def test_validate_token_expired(
    db_session: AsyncSession,
    test_user: User,
) -> None:
    """Test validation fails for an expired token."""
    plain = await PasswordResetService.create_reset_token(db_session, test_user)
    hash_val = PasswordResetService.hash_token(plain)

    # Make token expired in the database
    result = await db_session.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_val)
    )
    db_token = result.scalar_one()
    db_token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    with pytest.raises(UnauthorizedException) as exc_info:
        await PasswordResetService.validate_token(db_session, plain)
    assert exc_info.value.detail == "Invalid or expired password reset token"


@pytest.mark.anyio
async def test_validate_token_already_used(
    db_session: AsyncSession,
    test_user: User,
) -> None:
    """Test validation fails for a token already used."""
    plain = await PasswordResetService.create_reset_token(db_session, test_user)
    hash_val = PasswordResetService.hash_token(plain)

    # Make token used in the database
    result = await db_session.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_val)
    )
    db_token = result.scalar_one()
    db_token.used_at = datetime.now(UTC)
    await db_session.commit()

    with pytest.raises(UnauthorizedException) as exc_info:
        await PasswordResetService.validate_token(db_session, plain)
    assert exc_info.value.detail == "Invalid or expired password reset token"


@pytest.mark.anyio
async def test_reset_password_success(
    db_session: AsyncSession,
    test_user: User,
) -> None:
    """Test successful password reset updates user password.

    Also verifies that it revokes all active refresh sessions.
    """
    # Pre-add some refresh sessions for user
    session_1 = RefreshToken(
        user_id=test_user.id,
        token_hash="hash1",  # noqa: S106
        jti="jti1",
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    session_2 = RefreshToken(
        user_id=test_user.id,
        token_hash="hash2",  # noqa: S106
        jti="jti2",
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db_session.add_all([session_1, session_2])
    await db_session.commit()

    # Create reset token
    plain = await PasswordResetService.create_reset_token(db_session, test_user)
    token_hash = PasswordResetService.hash_token(plain)

    # Reset password
    await PasswordResetService.reset_password(db_session, plain, NEW_TEST_PASSWORD)

    # Verify password was updated
    await db_session.refresh(test_user)
    assert test_user.hashed_password is not None
    assert verify_password(NEW_TEST_PASSWORD, test_user.hashed_password)

    # Verify token was marked used
    result = await db_session.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    db_token = result.scalar_one()
    assert db_token.used_at is not None

    # Verify refresh sessions were revoked
    sessions = await RefreshTokenService.get_active_sessions_for_user(
        db_session, test_user.id
    )
    assert len(sessions) == 0

    # Ensure sessions have revoked_at timestamp set
    res = await db_session.execute(
        select(RefreshToken).where(RefreshToken.user_id == test_user.id)
    )
    db_sessions = res.scalars().all()
    assert len(db_sessions) == 2
    for s in db_sessions:
        assert s.revoked_at is not None


@pytest.mark.anyio
async def test_cleanup_expired_tokens(
    db_session: AsyncSession,
    test_user: User,
) -> None:
    """Test that cleanup deletes expired and already used tokens.

    Also ensures that it preserves valid unused ones.
    """
    now = datetime.now(UTC)

    # 1. Expired unused token
    t1 = PasswordResetToken(
        user_id=test_user.id,
        token_hash="hash1",  # noqa: S106
        expires_at=now - timedelta(minutes=1),
        used_at=None,
    )
    # 2. Expired used token
    t2 = PasswordResetToken(
        user_id=test_user.id,
        token_hash="hash2",  # noqa: S106
        expires_at=now - timedelta(minutes=1),
        used_at=now - timedelta(minutes=2),
    )
    # 3. Non-expired used token
    t3 = PasswordResetToken(
        user_id=test_user.id,
        token_hash="hash3",  # noqa: S106
        expires_at=now + timedelta(minutes=15),
        used_at=now - timedelta(seconds=10),
    )
    # 4. Non-expired unused token (valid)
    t4 = PasswordResetToken(
        user_id=test_user.id,
        token_hash="hash4",  # noqa: S106
        expires_at=now + timedelta(minutes=15),
        used_at=None,
    )

    db_session.add_all([t1, t2, t3, t4])
    await db_session.commit()

    deleted = await PasswordResetService.cleanup_expired_tokens(db_session)
    assert deleted == 3

    # Only t4 should remain in database
    result = await db_session.execute(select(PasswordResetToken))
    remaining = result.scalars().all()
    assert len(remaining) == 1
    assert remaining[0].token_hash == "hash4"  # noqa: S105


# =====================================================================
# API Endpoints Integration Tests
# =====================================================================


@pytest.mark.anyio
async def test_forgot_password_existing_email(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
) -> None:
    """Test forgot-password endpoint with an existing email address."""
    with patch(
        "ai_trading_discipline_copilot.services.email_service.EmailService.send_email"
    ) as mock_send:
        response = await client.post(
            "/auth/forgot-password",
            json={"email": test_user.email},
        )
        assert response.status_code == 200
        assert response.json()["message"] == (
            "If an account with that email exists, a password reset link has been sent."
        )

        # Check database: reset token should have been created
        result = await db_session.execute(
            select(PasswordResetToken).where(PasswordResetToken.user_id == test_user.id)
        )
        token = result.scalar_one_or_none()
        assert token is not None
        assert token.used_at is None

        # Verify email send was called
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs["to"] == test_user.email
        assert "Reset your password" in call_kwargs["subject"]
        assert "Reset Password" in call_kwargs["html"]
        assert "/#/reset-password/" in call_kwargs["html"]


@pytest.mark.anyio
async def test_forgot_password_non_existing_email(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Test forgot-password endpoint with a non-existing email address."""
    with patch(
        "ai_trading_discipline_copilot.services.email_service.EmailService.send_email"
    ) as mock_send:
        response = await client.post(
            "/auth/forgot-password",
            json={"email": "nonexisting_user_email@example.com"},
        )
        assert response.status_code == 200
        assert response.json()["message"] == (
            "If an account with that email exists, a password reset link has been sent."
        )

        # Verify no email send was called
        mock_send.assert_not_called()


@pytest.mark.anyio
async def test_reset_password_endpoint_success(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
) -> None:
    """Test successful password reset endpoint."""
    # Pre-add refresh session
    session = RefreshToken(
        user_id=test_user.id,
        token_hash="hash_val",  # noqa: S106
        jti="jti_val",
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db_session.add(session)
    await db_session.commit()

    # Generate token
    plain = await PasswordResetService.create_reset_token(db_session, test_user)

    response = await client.post(
        "/auth/reset-password",
        json={"token": plain, "new_password": NEW_TEST_PASSWORD},
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Password reset successful."

    # Verify refresh sessions were revoked
    sessions = await RefreshTokenService.get_active_sessions_for_user(
        db_session, test_user.id
    )
    assert len(sessions) == 0

    # Login fails with old password
    login_response_old = await client.post(
        "/auth/login",
        data={"username": test_user.username, "password": TEST_PASSWORD},
    )
    assert login_response_old.status_code == 401
    assert login_response_old.json()["detail"] == "Invalid username or password"

    # Login succeeds with new password
    login_response_new = await client.post(
        "/auth/login",
        data={"username": test_user.username, "password": NEW_TEST_PASSWORD},
    )
    assert login_response_new.status_code == 200
    assert "access_token" in login_response_new.json()


@pytest.mark.anyio
async def test_reset_password_endpoint_invalid_token(
    client: AsyncClient,
) -> None:
    """Test reset-password endpoint with an invalid token."""
    response = await client.post(
        "/auth/reset-password",
        json={"token": "invalidtoken" * 3, "new_password": NEW_TEST_PASSWORD},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired password reset token"


@pytest.mark.anyio
async def test_reset_password_endpoint_expired_token(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
) -> None:
    """Test reset-password endpoint with an expired token."""
    plain = await PasswordResetService.create_reset_token(db_session, test_user)
    token_hash = PasswordResetService.hash_token(plain)

    # Expire token in DB
    result = await db_session.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    db_token = result.scalar_one()
    db_token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    response = await client.post(
        "/auth/reset-password",
        json={"token": plain, "new_password": NEW_TEST_PASSWORD},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired password reset token"


@pytest.mark.anyio
async def test_reset_password_endpoint_already_used_token(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
) -> None:
    """Test reset-password endpoint with an already used token."""
    plain = await PasswordResetService.create_reset_token(db_session, test_user)
    token_hash = PasswordResetService.hash_token(plain)

    # Use token in DB
    result = await db_session.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    db_token = result.scalar_one()
    db_token.used_at = datetime.now(UTC)
    await db_session.commit()

    response = await client.post(
        "/auth/reset-password",
        json={"token": plain, "new_password": NEW_TEST_PASSWORD},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired password reset token"


@pytest.mark.anyio
async def test_forgot_password_email_failure_logged(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
) -> None:
    """Test requesting reset succeeds even if background email fails.

    Verifies that the error is logged.
    """
    with (
        patch(
            "ai_trading_discipline_copilot.services.email_service.EmailService.send_email",
            side_effect=Exception("Resend API key invalid"),
        ),
        patch(
            "ai_trading_discipline_copilot.routers.auth.logger.exception"
        ) as mock_log,
    ):
        response = await client.post(
            "/auth/forgot-password",
            json={"email": test_user.email},
        )
        assert response.status_code == 200
        assert "password reset link has been sent" in response.json()["message"]

        # Logged failure with password_reset context
        mock_log.assert_called_once()
        log_args = mock_log.call_args[0]
        assert "Failed to send email [type=password_reset]" in log_args[0]
