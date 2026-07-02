"""FastAPI dependency injection — database sessions and authenticated user."""

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

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_db() -> AsyncGenerator[AsyncSession]:
    """Yield one async database session per request.

    Rolls back automatically on any unhandled exception and always
    closes the session when the request completes.
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Decode the JWT and return the authenticated User.

    Raises UnauthorizedException (401) if the token is invalid or expired,
    the user does not exist, or the account is inactive.
    """
    # Lazy import prevents a circular dependency:
    # core/dependencies → models/user → models/base
    from ..models.user import User  # noqa: PLC0415

    user_id = decode_access_token(token)
    if not user_id:
        raise UnauthorizedException("Could not validate credentials")

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise UnauthorizedException("Could not validate credentials") from None

    result = await db.execute(select(User).where(User.id == uid))
    user: User | None = result.scalar_one_or_none()

    if user is None:
        raise UnauthorizedException("Could not validate credentials")

    if not user.is_active:
        raise UnauthorizedException("Could not validate credentials")

    return user


DbDep = Annotated[AsyncSession, Depends(get_db)]
