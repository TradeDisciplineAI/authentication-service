# ------------------ User Service Feature -----------------------
"""
Business logic service managing user account registration, unique username/email validation,
offloaded password hashing, and user model persistence.
"""

import asyncio
import logging

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_trading_discipline_copilot.core.exceptions import ConflictException
from ai_trading_discipline_copilot.core.security import hash_password
from ai_trading_discipline_copilot.models.user import User
from ai_trading_discipline_copilot.schemas.user import UserCreate

logger = logging.getLogger(__name__)


# ------------------ User Service Class -----------------------
class UserService:
    """
    User Management Service handling account registration and unique username/email verification.
    """

    # ------------------ Register User Method -----------------------
    @staticmethod
    async def register_user(
        db: AsyncSession,
        user_data: UserCreate,
    ) -> User:
        """
        Registers a new user account: offloads bcrypt password hashing to worker thread,
        verifies username and email uniqueness, creates unverified user instance, and commits to DB.
        """
        hashed_pw = await asyncio.to_thread(hash_password, user_data.password)

        result = await db.execute(
            select(User).where(
                or_(
                    User.username == user_data.username,
                    User.email == user_data.email,
                )
            )
        )

        existing_users = result.scalars().all()

        if existing_users:
            if any(u.username == user_data.username for u in existing_users):
                logger.warning(
                    "Registration failed: Username '%s' already exists",
                    user_data.username,
                )
                raise ConflictException("Username already exists")
            logger.warning(
                "Registration failed: Email '%s' already exists", user_data.email
            )
            raise ConflictException("Email already exists")

        user = User(
            username=user_data.username,
            email=user_data.email,
            hashed_password=hashed_pw,
            is_verified=False,
        )

        db.add(user)
        await db.commit()
        await db.refresh(user)

        logger.info(
            "Successfully registered user '%s' (ID: %s)", user.username, user.id
        )
        return user
