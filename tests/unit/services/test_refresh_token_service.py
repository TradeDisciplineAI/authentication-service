import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ai_trading_discipline_copilot.core.exceptions import UnauthorizedException
from ai_trading_discipline_copilot.models.refresh_token import RefreshToken
from ai_trading_discipline_copilot.models.user import User
from ai_trading_discipline_copilot.services.refresh_token_service import (
    RefreshTokenService,
    TokenPair,
)


@pytest.mark.anyio
async def test_create_session_commit() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    user = User(id=uuid.uuid4(), username="testuser")
    token_hash = "token_hash_abc"
    jti = "some-jti-uuid"

    # Act
    session = await RefreshTokenService.create_session(
        db=mock_db,
        user=user,
        token_hash=token_hash,
        jti=jti,
        ip_address="127.0.0.1",
        user_agent="Mozilla",
        device_name="Chrome",
        commit=True,
    )

    # Assert
    assert session.user_id == user.id
    assert session.token_hash == token_hash
    assert session.jti == jti
    assert session.ip_address == "127.0.0.1"
    assert session.user_agent == "Mozilla"
    assert session.device_name == "Chrome"
    mock_db.add.assert_called_once_with(session)
    mock_db.commit.assert_called_once()
    mock_db.refresh.assert_called_once_with(session)


@pytest.mark.anyio
async def test_create_session_no_commit() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()

    user = User(id=uuid.uuid4(), username="testuser")
    token_hash = "token_hash_abc"
    jti = "some-jti-uuid"

    # Act
    session = await RefreshTokenService.create_session(
        db=mock_db,
        user=user,
        token_hash=token_hash,
        jti=jti,
        commit=False,
    )

    # Assert
    assert session.user_id == user.id
    mock_db.add.assert_called_once_with(session)
    mock_db.flush.assert_called_once()


@pytest.mark.anyio
async def test_get_by_jti() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.execute = AsyncMock()

    mock_result = MagicMock()
    mock_session = RefreshToken(id=uuid.uuid4(), jti="target-jti")
    mock_result.scalar_one_or_none.return_value = mock_session
    mock_db.execute.return_value = mock_result

    # Act
    result = await RefreshTokenService.get_by_jti(mock_db, "target-jti")

    # Assert
    assert result == mock_session
    mock_db.execute.assert_called_once()


@pytest.mark.anyio
async def test_get_by_id() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.execute = AsyncMock()

    session_id = uuid.uuid4()
    mock_result = MagicMock()
    mock_session = RefreshToken(id=session_id, jti="some-jti")
    mock_result.scalar_one_or_none.return_value = mock_session
    mock_db.execute.return_value = mock_result

    # Act
    result = await RefreshTokenService.get_by_id(mock_db, session_id)

    # Assert
    assert result == mock_session
    mock_db.execute.assert_called_once()


@pytest.mark.anyio
async def test_get_active_sessions_for_user() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.execute = AsyncMock()

    user_id = uuid.uuid4()
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_sessions = [RefreshToken(id=uuid.uuid4(), user_id=user_id)]
    mock_scalars.all.return_value = mock_sessions
    mock_result.scalars.return_value = mock_scalars
    mock_db.execute.return_value = mock_result

    # Act
    result = await RefreshTokenService.get_active_sessions_for_user(mock_db, user_id)

    # Assert
    assert result == mock_sessions
    mock_db.execute.assert_called_once()


@pytest.mark.anyio
async def test_revoke() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.commit = AsyncMock()
    session = RefreshToken(id=uuid.uuid4(), jti="some-jti")

    # Act
    await RefreshTokenService.revoke(mock_db, session, commit=True)

    # Assert
    assert session.revoked_at is not None
    mock_db.commit.assert_called_once()


@pytest.mark.anyio
async def test_revoke_all_for_user() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()
    user_id = uuid.uuid4()

    # Act
    await RefreshTokenService.revoke_all_for_user(mock_db, user_id)

    # Assert
    mock_db.execute.assert_called_once()
    mock_db.commit.assert_called_once()


@pytest.mark.anyio
async def test_update_last_used() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.commit = AsyncMock()
    session = RefreshToken(id=uuid.uuid4(), jti="some-jti")

    # Act
    await RefreshTokenService.update_last_used(mock_db, session, commit=True)

    # Assert
    assert session.last_used_at is not None
    mock_db.commit.assert_called_once()


@pytest.mark.anyio
async def test_cleanup_expired_sessions() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    mock_result = MagicMock()
    mock_result.rowcount = 5
    mock_db.execute.return_value = mock_result

    # Act
    count = await RefreshTokenService.cleanup_expired_sessions(mock_db)

    # Assert
    assert count == 5
    mock_db.execute.assert_called_once()
    mock_db.commit.assert_called_once()


@pytest.mark.anyio
async def test_rotate_invalid_payload() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)

    with patch(
        "ai_trading_discipline_copilot.services.refresh_token_service.decode_refresh_token"
    ) as mock_decode:
        mock_decode.return_value = None  # Invalid signature/payload

        # Act & Assert
        with pytest.raises(UnauthorizedException, match="Invalid refresh token"):
            await RefreshTokenService.rotate(mock_db, "invalid-token")


@pytest.mark.anyio
async def test_rotate_missing_sub_or_jti() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)

    with patch(
        "ai_trading_discipline_copilot.services.refresh_token_service.decode_refresh_token"
    ) as mock_decode:
        mock_decode.return_value = {"sub": "some-user"}  # missing jti

        # Act & Assert
        with pytest.raises(UnauthorizedException, match="Invalid refresh token"):
            await RefreshTokenService.rotate(mock_db, "invalid-token")


@pytest.mark.anyio
async def test_rotate_session_not_found() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)

    with (
        patch(
            "ai_trading_discipline_copilot.services.refresh_token_service.decode_refresh_token"
        ) as mock_decode,
        patch(
            "ai_trading_discipline_copilot.services.refresh_token_service.RefreshTokenService.get_by_jti"
        ) as mock_get_session,
    ):
        mock_decode.return_value = {"sub": "user-uuid", "jti": "jti-uuid"}
        mock_get_session.return_value = None  # Session not in DB

        # Act & Assert
        with pytest.raises(UnauthorizedException, match="Refresh session not found"):
            await RefreshTokenService.rotate(mock_db, "some-token")


@pytest.mark.anyio
async def test_rotate_token_reuse_detected() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    user_id = uuid.uuid4()
    session = RefreshToken(
        id=uuid.uuid4(), user_id=user_id, jti="jti-uuid", revoked_at=datetime.now(UTC)
    )

    with (
        patch(
            "ai_trading_discipline_copilot.services.refresh_token_service.decode_refresh_token"
        ) as mock_decode,
        patch(
            "ai_trading_discipline_copilot.services.refresh_token_service.RefreshTokenService.get_by_jti"
        ) as mock_get_session,
        patch(
            "ai_trading_discipline_copilot.services.refresh_token_service.RefreshTokenService.revoke_all_for_user"
        ) as mock_revoke_all,
    ):
        mock_decode.return_value = {"sub": str(user_id), "jti": "jti-uuid"}
        mock_get_session.return_value = session

        # Act & Assert
        with pytest.raises(
            UnauthorizedException,
            match="Refresh token has been revoked due to reuse detection",
        ):
            await RefreshTokenService.rotate(mock_db, "some-token")

        mock_revoke_all.assert_called_once_with(db=mock_db, user_id=user_id)


@pytest.mark.anyio
async def test_rotate_token_expired() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    user_id = uuid.uuid4()
    session = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_id,
        jti="jti-uuid",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),  # Expired
    )

    with (
        patch(
            "ai_trading_discipline_copilot.services.refresh_token_service.decode_refresh_token"
        ) as mock_decode,
        patch(
            "ai_trading_discipline_copilot.services.refresh_token_service.RefreshTokenService.get_by_jti"
        ) as mock_get_session,
    ):
        mock_decode.return_value = {"sub": str(user_id), "jti": "jti-uuid"}
        mock_get_session.return_value = session

        # Act & Assert
        with pytest.raises(UnauthorizedException, match="Refresh token has expired"):
            await RefreshTokenService.rotate(mock_db, "some-token")


@pytest.mark.anyio
async def test_rotate_verify_hash_failed() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    user_id = uuid.uuid4()
    session = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_id,
        jti="jti-uuid",
        token_hash="hash-in-db",
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )

    with (
        patch(
            "ai_trading_discipline_copilot.services.refresh_token_service.decode_refresh_token"
        ) as mock_decode,
        patch(
            "ai_trading_discipline_copilot.services.refresh_token_service.RefreshTokenService.get_by_jti"
        ) as mock_get_session,
        patch(
            "ai_trading_discipline_copilot.services.refresh_token_service.verify_refresh_token"
        ) as mock_verify,
    ):
        mock_decode.return_value = {"sub": str(user_id), "jti": "jti-uuid"}
        mock_get_session.return_value = session
        mock_verify.return_value = False  # verification failed

        # Act & Assert
        with pytest.raises(UnauthorizedException, match="Invalid refresh token"):
            await RefreshTokenService.rotate(mock_db, "some-token")


@pytest.mark.anyio
async def test_rotate_user_not_found() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.execute = AsyncMock()
    user_id = uuid.uuid4()
    session = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_id,
        jti="jti-uuid",
        token_hash="hash-in-db",
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None  # User not found in DB
    mock_db.execute.return_value = mock_result

    with (
        patch(
            "ai_trading_discipline_copilot.services.refresh_token_service.decode_refresh_token"
        ) as mock_decode,
        patch(
            "ai_trading_discipline_copilot.services.refresh_token_service.RefreshTokenService.get_by_jti"
        ) as mock_get_session,
        patch(
            "ai_trading_discipline_copilot.services.refresh_token_service.verify_refresh_token"
        ) as mock_verify,
    ):
        mock_decode.return_value = {"sub": str(user_id), "jti": "jti-uuid"}
        mock_get_session.return_value = session
        mock_verify.return_value = True

        # Act & Assert
        with pytest.raises(UnauthorizedException, match="User not found"):
            await RefreshTokenService.rotate(mock_db, "some-token")


@pytest.mark.anyio
async def test_rotate_user_inactive() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.execute = AsyncMock()
    user_id = uuid.uuid4()
    session = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_id,
        jti="jti-uuid",
        token_hash="hash-in-db",
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )

    inactive_user = User(id=user_id, username="disabled", is_active=False)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = inactive_user
    mock_db.execute.return_value = mock_result

    with (
        patch(
            "ai_trading_discipline_copilot.services.refresh_token_service.decode_refresh_token"
        ) as mock_decode,
        patch(
            "ai_trading_discipline_copilot.services.refresh_token_service.RefreshTokenService.get_by_jti"
        ) as mock_get_session,
        patch(
            "ai_trading_discipline_copilot.services.refresh_token_service.verify_refresh_token"
        ) as mock_verify,
    ):
        mock_decode.return_value = {"sub": str(user_id), "jti": "jti-uuid"}
        mock_get_session.return_value = session
        mock_verify.return_value = True

        # Act & Assert
        with pytest.raises(UnauthorizedException, match="User account is disabled"):
            await RefreshTokenService.rotate(mock_db, "some-token")


@pytest.mark.anyio
async def test_rotate_success() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    user_id = uuid.uuid4()
    session = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_id,
        jti="jti-uuid",
        token_hash="hash-in-db",
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )

    active_user = User(id=user_id, username="activeuser", is_active=True)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = active_user
    mock_db.execute.return_value = mock_result

    with (
        patch(
            "ai_trading_discipline_copilot.services.refresh_token_service.decode_refresh_token"
        ) as mock_decode,
        patch(
            "ai_trading_discipline_copilot.services.refresh_token_service.RefreshTokenService.get_by_jti"
        ) as mock_get_session,
        patch(
            "ai_trading_discipline_copilot.services.refresh_token_service.verify_refresh_token"
        ) as mock_verify,
        patch(
            "ai_trading_discipline_copilot.services.refresh_token_service.create_access_token"
        ) as mock_create_access,
        patch(
            "ai_trading_discipline_copilot.services.refresh_token_service.create_refresh_token"
        ) as mock_create_refresh,
        patch(
            "ai_trading_discipline_copilot.services.refresh_token_service.RefreshTokenService.revoke"
        ) as mock_revoke_old,
        patch(
            "ai_trading_discipline_copilot.services.refresh_token_service.RefreshTokenService.create_session"
        ) as mock_create_sess,
    ):
        mock_decode.return_value = {"sub": str(user_id), "jti": "jti-uuid"}
        mock_get_session.return_value = session
        mock_verify.return_value = True
        mock_create_access.return_value = ("new-access-token", "access-jti")
        mock_create_refresh.return_value = ("new-refresh-token", "new-jti-uuid")

        new_session = RefreshToken(id=uuid.uuid4(), jti="new-jti-uuid")
        mock_create_sess.return_value = new_session

        # Act
        token_pair = await RefreshTokenService.rotate(
            db=mock_db,
            refresh_token="old-token",
            ip_address="192.168.1.1",
            user_agent="Firefox",
            device_name="Linux Desktop",
        )

        # Assert
        assert isinstance(token_pair, TokenPair)
        assert token_pair.access_token == "new-access-token"
        assert token_pair.refresh_token == "new-refresh-token"

        mock_revoke_old.assert_called_once_with(
            db=mock_db, session=session, commit=False
        )
        mock_create_sess.assert_called_once_with(
            db=mock_db,
            user=active_user,
            token_hash=ANY,
            jti="new-jti-uuid",
            ip_address="192.168.1.1",
            user_agent="Firefox",
            device_name="Linux Desktop",
            commit=False,
        )
        mock_db.commit.assert_called_once()
        mock_db.refresh.assert_called_once_with(new_session)
