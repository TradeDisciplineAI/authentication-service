from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_trading_discipline_copilot.models.email_verification_token import (
    EmailVerificationToken,
)
from ai_trading_discipline_copilot.models.user import User
from ai_trading_discipline_copilot.services.email_verification_service import (
    EmailVerificationService,
)

TEST_PASSWORD = "StrongPass1!"  # noqa: S105


@pytest.fixture
async def unverified_user(db_session: AsyncSession) -> User:
    """Create an unverified test user in the database."""
    from ai_trading_discipline_copilot.core.security import hash_password

    user = User(
        username="unverified",
        email="unverified@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
        is_verified=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.anyio
async def test_register_sends_verification_email(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Test that registration automatically generates token and queues email."""
    payload = {
        "username": "newreg",
        "email": "newreg@example.com",
        "password": TEST_PASSWORD,
    }
    with patch(
        "ai_trading_discipline_copilot.services.email_service.EmailService.send_verification_email"
    ) as mock_send:
        response = await client.post("/auth/register", json=payload)
        assert response.status_code == 201

        # Check user is created with is_verified=False
        result = await db_session.execute(
            select(User).where(User.username == "newreg")
        )
        user = result.scalar_one_or_none()
        assert user is not None
        assert user.is_verified is False

        # Verify token created in DB
        result_token = await db_session.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.user_id == user.id
            )
        )
        token = result_token.scalar_one_or_none()
        assert token is not None
        assert token.used_at is None

        # Verify email task was triggered
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs["to"] == "newreg@example.com"
        assert "/verify-email?token=" in call_kwargs["verification_url"]


@pytest.mark.anyio
async def test_verify_email_success(
    client: AsyncClient,
    db_session: AsyncSession,
    unverified_user: User,
) -> None:
    """Test successful email verification endpoint."""
    plain = await EmailVerificationService.create_verification_token(
        db_session, unverified_user
    )

    response = await client.post(
        "/auth/verify-email",
        json={"token": plain},
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Email verified successfully."
    assert "access_token" in response.json()
    assert response.json()["token_type"] == "bearer"
    assert "refresh_token" in response.cookies

    # Check database changes
    await db_session.refresh(unverified_user)
    assert unverified_user.is_verified is True

    token_hash = EmailVerificationService.hash_token(plain)
    result = await db_session.execute(
        select(EmailVerificationToken).where(
            EmailVerificationToken.token_hash == token_hash
        )
    )
    db_token = result.scalar_one()
    assert db_token.used_at is not None


@pytest.mark.anyio
async def test_verify_email_invalid_token(
    client: AsyncClient,
) -> None:
    """Test verify-email endpoint fails with invalid token."""
    response = await client.post(
        "/auth/verify-email",
        json={"token": "invalidtoken" * 3},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired email verification token"


@pytest.mark.anyio
async def test_verify_email_expired_token(
    client: AsyncClient,
    db_session: AsyncSession,
    unverified_user: User,
) -> None:
    """Test verify-email endpoint fails with expired token."""
    plain = await EmailVerificationService.create_verification_token(
        db_session, unverified_user
    )
    token_hash = EmailVerificationService.hash_token(plain)

    # Expire token in DB
    result = await db_session.execute(
        select(EmailVerificationToken).where(
            EmailVerificationToken.token_hash == token_hash
        )
    )
    db_token = result.scalar_one()
    db_token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    response = await client.post(
        "/auth/verify-email",
        json={"token": plain},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired email verification token"


@pytest.mark.anyio
async def test_verify_email_already_used_token(
    client: AsyncClient,
    db_session: AsyncSession,
    unverified_user: User,
) -> None:
    """Test verify-email endpoint fails with already used token."""
    plain = await EmailVerificationService.create_verification_token(
        db_session, unverified_user
    )
    token_hash = EmailVerificationService.hash_token(plain)

    # Mark token used in DB
    result = await db_session.execute(
        select(EmailVerificationToken).where(
            EmailVerificationToken.token_hash == token_hash
        )
    )
    db_token = result.scalar_one()
    db_token.used_at = datetime.now(UTC)
    await db_session.commit()

    response = await client.post(
        "/auth/verify-email",
        json={"token": plain},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired email verification token"


@pytest.mark.anyio
async def test_login_before_verification_fails(
    client: AsyncClient,
    unverified_user: User,
) -> None:
    """Test that login attempts for unverified users return 403 Forbidden."""
    response = await client.post(
        "/auth/login",
        data={"username": unverified_user.username, "password": TEST_PASSWORD},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Please verify your email before logging in."


@pytest.mark.anyio
async def test_login_after_verification_succeeds(
    client: AsyncClient,
    db_session: AsyncSession,
    unverified_user: User,
) -> None:
    """Test that login succeeds once user is verified."""
    # Verify user
    unverified_user.is_verified = True
    await db_session.commit()

    response = await client.post(
        "/auth/login",
        data={"username": unverified_user.username, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


@pytest.mark.anyio
async def test_resend_verification_success(
    client: AsyncClient,
    db_session: AsyncSession,
    unverified_user: User,
) -> None:
    """Test resending verification link to unverified user."""
    # Pre-create token to test deletion of previous token
    await EmailVerificationService.create_verification_token(
        db_session, unverified_user
    )

    with patch(
        "ai_trading_discipline_copilot.services.email_service.EmailService.send_verification_email"
    ) as mock_send:
        response = await client.post(
            "/auth/resend-verification",
            json={"username_or_email": unverified_user.email},
        )
        assert response.status_code == 200
        assert response.json()["message"] == "Verification email sent."

        # Verify email was sent
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs["to"] == unverified_user.email

        # Verify old token deleted and only 1 remains
        result = await db_session.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.user_id == unverified_user.id
            )
        )
        remaining = result.scalars().all()
        assert len(remaining) == 1


@pytest.mark.anyio
async def test_resend_verification_already_verified(
    client: AsyncClient,
    db_session: AsyncSession,
    unverified_user: User,
) -> None:
    """Test resending to already verified user returns success but sends no email."""
    unverified_user.is_verified = True
    await db_session.commit()

    with patch(
        "ai_trading_discipline_copilot.services.email_service.EmailService.send_verification_email"
    ) as mock_send:
        response = await client.post(
            "/auth/resend-verification",
            json={"username_or_email": unverified_user.email},
        )
        assert response.status_code == 200
        assert response.json()["message"] == "Verification email sent."

        # Verify no email was sent
        mock_send.assert_not_called()


@pytest.mark.anyio
async def test_resend_verification_non_existing_email(
    client: AsyncClient,
) -> None:
    """Test resending to non-existent email returns success but sends no email."""
    with patch(
        "ai_trading_discipline_copilot.services.email_service.EmailService.send_verification_email"
    ) as mock_send:
        response = await client.post(
            "/auth/resend-verification",
            json={"username_or_email": "notfound@example.com"},
        )
        assert response.status_code == 200
        assert response.json()["message"] == "Verification email sent."

        # Verify no email was sent
        mock_send.assert_not_called()


@pytest.mark.anyio
async def test_resend_verification_by_username(
    client: AsyncClient,
    db_session: AsyncSession,
    unverified_user: User,
) -> None:
    """Test resending verification link using username instead of email."""
    with patch(
        "ai_trading_discipline_copilot.services.email_service.EmailService.send_verification_email"
    ) as mock_send:
        response = await client.post(
            "/auth/resend-verification",
            json={"username_or_email": unverified_user.username},
        )
        assert response.status_code == 200
        assert response.json()["message"] == "Verification email sent."
        mock_send.assert_called_once()


@pytest.mark.anyio
async def test_cleanup_expired_tokens(
    db_session: AsyncSession,
    unverified_user: User,
) -> None:
    """Test cleanup function deletes used/expired verification tokens."""
    now = datetime.now(UTC)

    # 1. Expired unused token
    t1 = EmailVerificationToken(
        user_id=unverified_user.id,
        token_hash="hash1",  # noqa: S106
        expires_at=now - timedelta(minutes=1),
        used_at=None,
    )
    # 2. Expired used token
    t2 = EmailVerificationToken(
        user_id=unverified_user.id,
        token_hash="hash2",  # noqa: S106
        expires_at=now - timedelta(minutes=1),
        used_at=now - timedelta(minutes=2),
    )
    # 3. Non-expired used token
    t3 = EmailVerificationToken(
        user_id=unverified_user.id,
        token_hash="hash3",  # noqa: S106
        expires_at=now + timedelta(hours=24),
        used_at=now - timedelta(seconds=10),
    )
    # 4. Non-expired unused token (valid)
    t4 = EmailVerificationToken(
        user_id=unverified_user.id,
        token_hash="hash4",  # noqa: S106
        expires_at=now + timedelta(hours=24),
        used_at=None,
    )

    db_session.add_all([t1, t2, t3, t4])
    await db_session.commit()

    deleted = await EmailVerificationService.cleanup_expired_tokens(db_session)
    assert deleted == 3

    # Only t4 remains
    result = await db_session.execute(select(EmailVerificationToken))
    remaining = result.scalars().all()
    assert len(remaining) == 1
    assert remaining[0].token_hash == "hash4"  # noqa: S105


@pytest.mark.anyio
async def test_register_verification_email_failure_logged(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Test registration succeeds even if background email fails.

    Verifies that the error is logged.
    """
    payload = {
        "username": "emailfail",
        "email": "emailfail@example.com",
        "password": TEST_PASSWORD,
    }

    with patch(
        "ai_trading_discipline_copilot.services.email_service.EmailService.send_verification_email",
        side_effect=Exception("SMTP or API connection timeout"),
    ), patch(
        "ai_trading_discipline_copilot.routers.auth.logger.exception"
    ) as mock_log:
        response = await client.post("/auth/register", json=payload)

        # Registration must still succeed immediately and return 201
        assert response.status_code == 201

        # User should still be created
        result = await db_session.execute(
            select(User).where(User.username == "emailfail")
        )
        user = result.scalar_one_or_none()
        assert user is not None
        assert user.is_verified is False

        # Verify logger.exception was called once with context
        mock_log.assert_called_once()
        log_args = mock_log.call_args[0]
        assert "Failed to send email [type=verification]" in log_args[0]


@pytest.mark.anyio
async def test_email_verification_service_direct(
    db_session: AsyncSession,
) -> None:
    """Test EmailVerificationService.verify_email directly in Python to verify logic and hit coverage."""
    from ai_trading_discipline_copilot.core.security import hash_password
    user = User(
        username="directuser",
        email="direct@example.com",
        hashed_password=hash_password("Pass123!"),
        is_verified=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    plain = await EmailVerificationService.create_verification_token(
        db_session, user
    )
    verified_user = await EmailVerificationService.verify_email(db_session, plain)
    assert verified_user.id == user.id
    assert verified_user.is_verified is True

