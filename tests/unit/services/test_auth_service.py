import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from fastapi import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ai_trading_discipline_copilot.core.config import get_settings
from ai_trading_discipline_copilot.core.exceptions import (
    ForbiddenException,
    UnauthorizedException,
)
from ai_trading_discipline_copilot.models.refresh_token import RefreshToken
from ai_trading_discipline_copilot.models.user import User
from ai_trading_discipline_copilot.schemas.user import Token
from ai_trading_discipline_copilot.services.auth_service import AuthService

settings = get_settings()


@pytest.mark.anyio
async def test_authenticate_user_lockout_active() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.execute = AsyncMock()

    user = User(
        id=uuid.uuid4(),
        username="lockeduser",
        lockout_until=datetime.now(UTC) + timedelta(minutes=5),
        failed_login_attempts=5,
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    mock_db.execute.return_value = mock_result

    # Act & Assert
    with pytest.raises(UnauthorizedException, match="Account is temporarily locked"):
        await AuthService._authenticate_user(mock_db, "lockeduser", "any-password")


@pytest.mark.anyio
async def test_authenticate_user_lockout_expired() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    user = User(
        id=uuid.uuid4(),
        username="expiredlockout",
        lockout_until=datetime.now(UTC) - timedelta(minutes=5),
        failed_login_attempts=5,
        hashed_password="hashed_password_val",
        is_active=True,
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    mock_db.execute.return_value = mock_result

    # Act
    with patch(
        "ai_trading_discipline_copilot.services.auth_service.verify_password",
        return_value=True,
    ):
        res = await AuthService._authenticate_user(
            mock_db, "expiredlockout", "correct-password"
        )

        # Assert
        assert res == user
        assert user.failed_login_attempts == 0
        assert user.lockout_until is None
        mock_db.commit.assert_called_once()


@pytest.mark.anyio
async def test_authenticate_user_not_found() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.execute = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    # Act & Assert
    with pytest.raises(UnauthorizedException, match="Invalid username or password"):
        await AuthService._authenticate_user(mock_db, "nonexistent", "password")


@pytest.mark.anyio
async def test_authenticate_user_wrong_password_lockout_trigger() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    user = User(
        id=uuid.uuid4(),
        username="user1",
        hashed_password="hashed_val",
        failed_login_attempts=settings.max_login_attempts - 1,
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    mock_db.execute.return_value = mock_result

    # Act & Assert
    with (
        patch(
            "ai_trading_discipline_copilot.services.auth_service.verify_password",
            return_value=False,
        ),
        pytest.raises(UnauthorizedException, match="Invalid username or password"),
    ):
        await AuthService._authenticate_user(mock_db, "user1", "wrong-password")

    # Assert account locked
    assert user.failed_login_attempts == settings.max_login_attempts
    assert user.lockout_until is not None
    mock_db.commit.assert_called_once()


@pytest.mark.anyio
async def test_authenticate_user_inactive() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    user = User(
        id=uuid.uuid4(),
        username="user1",
        hashed_password="hashed_val",
        is_active=False,
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    mock_db.execute.return_value = mock_result

    # Act & Assert
    with (
        patch(
            "ai_trading_discipline_copilot.services.auth_service.verify_password",
            return_value=True,
        ),
        pytest.raises(UnauthorizedException, match="User account is disabled"),
    ):
        await AuthService._authenticate_user(mock_db, "user1", "correct-password")


def test_create_tokens() -> None:
    # Arrange
    user = User(id=uuid.uuid4())

    with (
        patch(
            "ai_trading_discipline_copilot.services.auth_service.create_access_token",
            return_value=("access", "access-jti"),
        ),
        patch(
            "ai_trading_discipline_copilot.services.auth_service.create_refresh_token",
            return_value=("refresh", "refresh-jti"),
        ),
    ):
        # Act
        access, refresh, jti = AuthService._create_tokens(user)

        # Assert
        assert access == "access"
        assert refresh == "refresh"
        assert jti == "refresh-jti"


def test_set_refresh_cookie() -> None:
    # Arrange
    mock_response = MagicMock(spec=Response)

    # Act
    AuthService.set_refresh_cookie(mock_response, "mock-refresh")

    # Assert
    mock_response.set_cookie.assert_called_once()


def test_delete_refresh_cookie() -> None:
    # Arrange
    mock_response = MagicMock(spec=Response)

    # Act
    AuthService.delete_refresh_cookie(mock_response)

    # Assert
    mock_response.delete_cookie.assert_called_once()


@pytest.mark.anyio
async def test_login_unverified_user() -> None:
    # Arrange
    mock_response = MagicMock(spec=Response)
    mock_db = MagicMock(spec=AsyncSession)

    unverified_user = User(id=uuid.uuid4(), is_verified=False)

    # Act & Assert
    with (
        patch(
            "ai_trading_discipline_copilot.services.auth_service.AuthService._authenticate_user",
            return_value=unverified_user,
        ),
        pytest.raises(ForbiddenException, match="Please verify your email"),
    ):
        await AuthService.login(mock_response, mock_db, "user", "pass")


@pytest.mark.anyio
async def test_login_success() -> None:
    # Arrange
    mock_response = MagicMock(spec=Response)
    mock_db = MagicMock(spec=AsyncSession)

    user = User(id=uuid.uuid4(), username="testuser", is_verified=True)

    with (
        patch(
            "ai_trading_discipline_copilot.services.auth_service.AuthService._authenticate_user",
            return_value=user,
        ),
        patch(
            "ai_trading_discipline_copilot.services.auth_service.AuthService._create_tokens",
            return_value=("access-tok", "refresh-tok", "jti-val"),
        ),
        patch(
            "ai_trading_discipline_copilot.services.auth_service.RefreshTokenService.create_session"
        ) as mock_create_session,
        patch(
            "ai_trading_discipline_copilot.services.auth_service.AuthService.set_refresh_cookie"
        ) as mock_set_cookie,
    ):
        # Act
        token = await AuthService.login(
            mock_response,
            mock_db,
            "testuser",
            "pass",
            ip_address="127.0.0.1",
            user_agent="Firefox",
            device_name="Laptop",
        )

        # Assert
        assert isinstance(token, Token)
        assert token.access_token == "access-tok"
        mock_create_session.assert_called_once_with(
            db=mock_db,
            user=user,
            token_hash=ANY,
            jti="jti-val",
            ip_address="127.0.0.1",
            user_agent="Firefox",
            device_name="Laptop",
        )
        mock_set_cookie.assert_called_once_with(
            response=mock_response,
            refresh_token="refresh-tok",
        )


@pytest.mark.anyio
async def test_logout_missing_token() -> None:
    # Arrange
    mock_response = MagicMock(spec=Response)
    mock_db = MagicMock(spec=AsyncSession)

    # Act & Assert
    with pytest.raises(UnauthorizedException, match="Missing refresh token"):
        await AuthService.logout(mock_response, mock_db, None)


@pytest.mark.anyio
async def test_logout_invalid_token_payload() -> None:
    # Arrange
    mock_response = MagicMock(spec=Response)
    mock_db = MagicMock(spec=AsyncSession)

    with (
        patch(
            "ai_trading_discipline_copilot.services.auth_service.decode_refresh_token",
            return_value=None,
        ),
        patch(
            "ai_trading_discipline_copilot.services.auth_service.AuthService.delete_refresh_cookie"
        ) as mock_delete,
    ):
        # Act & Assert
        with pytest.raises(UnauthorizedException, match="Invalid refresh token"):
            await AuthService.logout(mock_response, mock_db, "invalid-token")

        mock_delete.assert_called_once_with(mock_response)


@pytest.mark.anyio
async def test_logout_success() -> None:
    # Arrange
    mock_response = MagicMock(spec=Response)
    mock_db = MagicMock(spec=AsyncSession)
    session = RefreshToken(id=uuid.uuid4(), jti="jti-val", user_id=uuid.uuid4())

    with (
        patch(
            "ai_trading_discipline_copilot.services.auth_service.decode_refresh_token",
            return_value={"jti": "jti-val"},
        ),
        patch(
            "ai_trading_discipline_copilot.services.auth_service.RefreshTokenService.get_by_jti",
            return_value=session,
        ),
        patch(
            "ai_trading_discipline_copilot.services.auth_service.RefreshTokenService.revoke"
        ) as mock_revoke,
        patch(
            "ai_trading_discipline_copilot.services.auth_service.AuthService.delete_refresh_cookie"
        ) as mock_delete,
    ):
        # Act
        await AuthService.logout(mock_response, mock_db, "valid-token")

        # Assert
        mock_revoke.assert_called_once_with(db=mock_db, session=session)
        mock_delete.assert_called_once_with(mock_response)


@pytest.mark.anyio
async def test_login_with_google_find_by_id_success() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.execute = AsyncMock()
    mock_response = MagicMock(spec=Response)

    user = User(
        id=uuid.uuid4(),
        username="googleuser",
        email="test@google.com",
        is_active=True,
        failed_login_attempts=2,
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    mock_db.execute.return_value = mock_result

    with (
        patch(
            "ai_trading_discipline_copilot.services.auth_service.AuthService._create_tokens",
            return_value=("access-tok", "refresh-tok", "jti-val"),
        ),
        patch(
            "ai_trading_discipline_copilot.services.auth_service.RefreshTokenService.create_session"
        ) as mock_create_sess,
        patch(
            "ai_trading_discipline_copilot.services.auth_service.AuthService.set_refresh_cookie"
        ) as mock_set_cookie,
        patch.object(mock_db, "commit", new_callable=AsyncMock) as mock_commit,
    ):
        # Act
        token = await AuthService.login_with_google(
            db=mock_db,
            google_id="g123",
            email="test@google.com",
            response=mock_response,
        )

        # Assert
        assert token.access_token == "access-tok"
        assert user.failed_login_attempts == 0
        mock_commit.assert_called_once()
        mock_create_sess.assert_called_once()
        mock_set_cookie.assert_called_once()


@pytest.mark.anyio
async def test_login_with_google_link_by_email() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.execute = AsyncMock()
    mock_response = MagicMock(spec=Response)

    # First find by google_id fails (None), second find by email succeeds (user)
    user = User(
        id=uuid.uuid4(),
        username="emailuser",
        email="test@google.com",
        is_active=True,
        google_id=None,
        failed_login_attempts=0,
    )

    mock_result_id = MagicMock()
    mock_result_id.scalar_one_or_none.return_value = None

    mock_result_email = MagicMock()
    mock_result_email.scalar_one_or_none.return_value = user

    mock_db.execute.side_effect = [mock_result_id, mock_result_email]

    with (
        patch(
            "ai_trading_discipline_copilot.services.auth_service.AuthService._create_tokens",
            return_value=("access-tok", "refresh-tok", "jti-val"),
        ),
        patch(
            "ai_trading_discipline_copilot.services.auth_service.RefreshTokenService.create_session"
        ) as mock_create_sess,
        patch(
            "ai_trading_discipline_copilot.services.auth_service.AuthService.set_refresh_cookie"
        ) as mock_set_cookie,
        patch.object(mock_db, "commit", new_callable=AsyncMock) as mock_commit,
    ):
        # Act
        token = await AuthService.login_with_google(
            db=mock_db,
            google_id="g123",
            email="test@google.com",
            response=mock_response,
        )

        # Assert
        assert token.access_token == "access-tok"
        assert user.google_id == "g123"
        assert user.is_verified is True
        assert mock_commit.call_count == 1  # linked commit
        mock_create_sess.assert_called_once()
        mock_set_cookie.assert_called_once()


@pytest.mark.anyio
async def test_login_with_google_register_new() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.execute = AsyncMock()
    mock_db.add = MagicMock()

    async def mock_refresh(obj: Any) -> None:
        if isinstance(obj, User):
            obj.is_active = True
            obj.failed_login_attempts = 0

    mock_db.refresh = AsyncMock(side_effect=mock_refresh)
    mock_response = MagicMock(spec=Response)

    # First query (by ID) returns None
    mock_res_id = MagicMock()
    mock_res_id.scalar_one_or_none.return_value = None

    # Second query (by email) returns None
    mock_res_email = MagicMock()
    mock_res_email.scalar_one_or_none.return_value = None

    # Username uniqueness queries:
    # 1. First choice username query: returns an existing user (duplicate!)
    dup_user = User(id=uuid.uuid4(), username="test")
    mock_res_dup = MagicMock()
    mock_res_dup.scalar_one_or_none.return_value = dup_user

    # 2. Second choice username query: returns None (unique!)
    mock_res_unique = MagicMock()
    mock_res_unique.scalar_one_or_none.return_value = None

    mock_db.execute.side_effect = [
        mock_res_id,
        mock_res_email,
        mock_res_dup,
        mock_res_unique,
    ]

    with (
        patch(
            "ai_trading_discipline_copilot.services.auth_service.AuthService._create_tokens",
            return_value=("access-tok", "refresh-tok", "jti-val"),
        ),
        patch(
            "ai_trading_discipline_copilot.services.auth_service.RefreshTokenService.create_session"
        ) as mock_create_sess,
        patch(
            "ai_trading_discipline_copilot.services.auth_service.AuthService.set_refresh_cookie"
        ) as mock_set_cookie,
        patch.object(mock_db, "commit", new_callable=AsyncMock) as mock_commit,
    ):
        # Act
        token = await AuthService.login_with_google(
            db=mock_db,
            google_id="g123",
            email="test@google.com",
            response=mock_response,
        )

        # Assert
        assert token.access_token == "access-tok"
        mock_db.add.assert_called_once()
        # 1 commit for registration, 1 commit for final login process (since login resets attempts and calls session creation)
        # Note: the code registers a user and calls db.commit(), and then (since it continues on to token issuing)
        # also runs mock_create_session which calls db.commit (if commit=True)
        assert mock_commit.call_count >= 1
        mock_create_sess.assert_called_once()
        mock_set_cookie.assert_called_once()


@pytest.mark.anyio
async def test_login_with_google_inactive_link_forbidden() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.execute = AsyncMock()
    mock_response = MagicMock(spec=Response)

    user = User(
        id=uuid.uuid4(),
        username="emailuser",
        email="test@google.com",
        is_active=False,
        google_id=None,
    )
    mock_res_id = MagicMock()
    mock_res_id.scalar_one_or_none.return_value = None
    mock_res_email = MagicMock()
    mock_res_email.scalar_one_or_none.return_value = user
    mock_db.execute.side_effect = [mock_res_id, mock_res_email]

    # Act & Assert
    with pytest.raises(ForbiddenException, match="User account is disabled"):
        await AuthService.login_with_google(
            db=mock_db,
            google_id="g123",
            email="test@google.com",
            response=mock_response,
        )


@pytest.mark.anyio
async def test_login_with_google_inactive_auth_forbidden() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.execute = AsyncMock()
    mock_response = MagicMock(spec=Response)

    user = User(
        id=uuid.uuid4(),
        username="googleuser",
        email="test@google.com",
        is_active=False,
        google_id="g123",
    )
    mock_res_id = MagicMock()
    mock_res_id.scalar_one_or_none.return_value = user
    mock_db.execute.return_value = mock_res_id

    # Act & Assert
    with pytest.raises(ForbiddenException, match="User account is disabled"):
        await AuthService.login_with_google(
            db=mock_db,
            google_id="g123",
            email="test@google.com",
            response=mock_response,
        )


@pytest.mark.anyio
async def test_authenticate_user_success_reset_attempts() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    user = User(
        id=uuid.uuid4(),
        username="user1",
        hashed_password="hashed_val",
        is_active=True,
        failed_login_attempts=2,
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    mock_db.execute.return_value = mock_result

    # Act
    with patch(
        "ai_trading_discipline_copilot.services.auth_service.verify_password",
        return_value=True,
    ):
        res = await AuthService._authenticate_user(mock_db, "user1", "correct-password")

        # Assert
        assert res == user
        assert user.failed_login_attempts == 0
        assert user.lockout_until is None
        mock_db.commit.assert_called_once()


@pytest.mark.anyio
async def test_logout_missing_jti() -> None:
    # Arrange
    mock_response = MagicMock(spec=Response)
    mock_db = MagicMock(spec=AsyncSession)

    with (
        patch(
            "ai_trading_discipline_copilot.services.auth_service.decode_refresh_token",
            return_value={"no_jti": "here"},
        ),
        patch(
            "ai_trading_discipline_copilot.services.auth_service.AuthService.delete_refresh_cookie"
        ) as mock_delete,
    ):
        # Act & Assert
        with pytest.raises(UnauthorizedException, match="Invalid refresh token"):
            await AuthService.logout(mock_response, mock_db, "valid-token-no-jti")

        mock_delete.assert_called_once_with(mock_response)


@pytest.mark.anyio
async def test_logout_already_revoked() -> None:
    # Arrange
    mock_response = MagicMock(spec=Response)
    mock_db = MagicMock(spec=AsyncSession)
    session = RefreshToken(
        id=uuid.uuid4(),
        jti="jti-val",
        user_id=uuid.uuid4(),
        revoked_at=datetime.now(UTC),
    )

    with (
        patch(
            "ai_trading_discipline_copilot.services.auth_service.decode_refresh_token",
            return_value={"jti": "jti-val"},
        ),
        patch(
            "ai_trading_discipline_copilot.services.auth_service.RefreshTokenService.get_by_jti",
            return_value=session,
        ),
        patch(
            "ai_trading_discipline_copilot.services.auth_service.RefreshTokenService.revoke"
        ) as mock_revoke,
        patch(
            "ai_trading_discipline_copilot.services.auth_service.AuthService.delete_refresh_cookie"
        ) as mock_delete,
    ):
        # Act
        await AuthService.logout(mock_response, mock_db, "valid-token")

        # Assert
        mock_revoke.assert_not_called()
        mock_delete.assert_called_once_with(mock_response)


@pytest.mark.anyio
async def test_login_with_google_fallback_username() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.execute = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.refresh = AsyncMock()
    mock_response = MagicMock(spec=Response)

    # First query (by ID) returns None
    mock_res_id = MagicMock()
    mock_res_id.scalar_one_or_none.return_value = None

    # Second query (by email) returns None
    mock_res_email = MagicMock()
    mock_res_email.scalar_one_or_none.return_value = None

    # Username uniqueness query: returns None (unique!)
    mock_res_unique = MagicMock()
    mock_res_unique.scalar_one_or_none.return_value = None

    mock_db.execute.side_effect = [mock_res_id, mock_res_email, mock_res_unique]

    async def mock_refresh(obj: Any) -> None:
        if isinstance(obj, User):
            obj.is_active = True
            obj.failed_login_attempts = 0

    mock_db.refresh = AsyncMock(side_effect=mock_refresh)

    with (
        patch(
            "ai_trading_discipline_copilot.services.auth_service.AuthService._create_tokens",
            return_value=("access-tok", "refresh-tok", "jti-val"),
        ),
        patch(
            "ai_trading_discipline_copilot.services.auth_service.RefreshTokenService.create_session"
        ),
        patch(
            "ai_trading_discipline_copilot.services.auth_service.AuthService.set_refresh_cookie"
        ),
        patch.object(mock_db, "commit", new_callable=AsyncMock),
    ):
        # Act
        # Using a special email where prefix is non-alphanumeric, e.g., "@@example.com"
        token = await AuthService.login_with_google(
            db=mock_db,
            google_id="g123",
            email="@@example.com",
            response=mock_response,
        )

        # Assert
        assert token.access_token == "access-tok"
        mock_db.add.assert_called_once()
        # Verify the fallback username "google_user" was used
        args, kwargs = mock_db.add.call_args
        registered_user = args[0]
        assert registered_user.username == "google_user"
