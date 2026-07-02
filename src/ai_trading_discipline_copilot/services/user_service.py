from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_trading_discipline_copilot.core.security import hash_password
from ai_trading_discipline_copilot.models.user import User
from ai_trading_discipline_copilot.schemas.user import UserCreate


class UserService:
    """Business logic for user management."""

    @staticmethod
    async def register_user(
        db: AsyncSession,
        user_data: UserCreate,
    ) -> User:
        """Register a new user."""

        # Check whether the username or email already exists.
        result = await db.execute(
            select(User).where(
                or_(
                    User.username == user_data.username,
                    User.email == user_data.email,
                )
            )
        )

        existing_user = result.scalar_one_or_none()

        if existing_user:
            if existing_user.username == user_data.username:
                raise ValueError("Username already exists")
            raise ValueError("Email already exists")

        user = User(
            username=user_data.username,
            email=user_data.email,
            hashed_password=hash_password(user_data.password),
        )

        db.add(user)
        await db.commit()
        await db.refresh(user)

        return user
