# ------------------ Core Dependencies Feature -----------------------
"""
FastAPI dependency injection utilities providing asynchronous database sessions
and authenticating active user credentials from JWT Bearer tokens.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import AsyncSessionFactory
from .exceptions import UnauthorizedException
from .security import decode_access_token

if TYPE_CHECKING:
    from ..models.user import User

# ------------------ OAuth2 Password Bearer Scheme -----------------------
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ------------------ Database Session Dependency -----------------------
async def get_db() -> AsyncGenerator[AsyncSession]:
    """
    Yields an isolated async database session per request and automatically rolls back
    transactions on unhandled exceptions before closing.
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


# ------------------ Get Current Authenticated User Dependency -----------------------
async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """
    Decodes the JWT access token from the Authorization header, validates the user ID subject,
    and returns the active User model instance from the database.
    """
    from ..models.user import User

    payload = decode_access_token(token)

    if payload is None:
        raise UnauthorizedException("Could not validate credentials")

    user_id = payload.get("sub")

    if user_id is None:
        raise UnauthorizedException("Could not validate credentials")

    try:
        uid = uuid.UUID(user_id)
    except (ValueError, TypeError):
        raise UnauthorizedException("Could not validate credentials") from None

    result = await db.execute(select(User).where(User.id == uid))

    user: User | None = result.scalar_one_or_none()

    if user is None:
        raise UnauthorizedException("Could not validate credentials")

    if not user.is_active:
        raise UnauthorizedException("Could not validate credentials")

    return user


DbDep = Annotated[AsyncSession, Depends(get_db)]
