from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ai_trading_discipline_copilot.core.exceptions import ConflictException
from ai_trading_discipline_copilot.models.user import User
from ai_trading_discipline_copilot.schemas.user import UserCreate
from ai_trading_discipline_copilot.services.user_service import UserService


@pytest.mark.anyio
async def test_register_user_success() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result.scalars.return_value = mock_scalars
    mock_db.execute.return_value = mock_result

    user_data = UserCreate(
        username="newuser",
        email="newuser@example.com",
        password="MySecurePassword123",
    )

    # Act
    with patch(
        "ai_trading_discipline_copilot.services.user_service.hash_password"
    ) as mock_hash:
        mock_hash.return_value = "hashed_mock_password"
        user = await UserService.register_user(mock_db, user_data)

        # Assert
        assert user is not None
        assert user.username == "newuser"
        assert user.email == "newuser@example.com"
        assert user.hashed_password == "hashed_mock_password"
        assert user.is_verified is False

        mock_hash.assert_called_once_with("MySecurePassword123")
        mock_db.add.assert_called_once_with(user)
        mock_db.commit.assert_called_once()
        mock_db.refresh.assert_called_once_with(user)


@pytest.mark.anyio
async def test_register_user_duplicate_username() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    # Mock DB response returning a user with duplicate username
    existing_user = User(
        username="duplicate",
        email="first@example.com",
        hashed_password="hashed_pw",
    )
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [existing_user]
    mock_result.scalars.return_value = mock_scalars
    mock_db.execute.return_value = mock_result

    user_data = UserCreate(
        username="duplicate",
        email="second@example.com",
        password="MySecurePassword123",
    )

    # Act & Assert
    with pytest.raises(ConflictException, match="Username already exists"):
        await UserService.register_user(mock_db, user_data)

    mock_db.commit.assert_not_called()
    mock_db.add.assert_not_called()


@pytest.mark.anyio
async def test_register_user_duplicate_email() -> None:
    # Arrange
    mock_db = MagicMock(spec=AsyncSession)
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    # Mock DB response returning a user with duplicate email
    existing_user = User(
        username="first",
        email="duplicate@example.com",
        hashed_password="hashed_pw",
    )
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [existing_user]
    mock_result.scalars.return_value = mock_scalars
    mock_db.execute.return_value = mock_result

    user_data = UserCreate(
        username="second",
        email="duplicate@example.com",
        password="MySecurePassword123",
    )

    # Act & Assert
    with pytest.raises(ConflictException, match="Email already exists"):
        await UserService.register_user(mock_db, user_data)

    mock_db.commit.assert_not_called()
    mock_db.add.assert_not_called()
