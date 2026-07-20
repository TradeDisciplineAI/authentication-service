"""Password reset service business logic."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ai_trading_discipline_copilot.core.exceptions import UnauthorizedException
from ai_trading_discipline_copilot.core.security import hash_password
from ai_trading_discipline_copilot.models.password_reset_token import PasswordResetToken
from ai_trading_discipline_copilot.services.refresh_token_service import (
    RefreshTokenService,
)

if TYPE_CHECKING:
    from ai_trading_discipline_copilot.models.user import User

logger = logging.getLogger(__name__)


class PasswordResetService:
    """Business logic for handling password resets."""

    @staticmethod
    def generate_token() -> str:
        """Generate a secure random token.

        Returns:
            str: A secure random URL-safe string.
        """
        return secrets.token_urlsafe(32)

    @staticmethod
    def hash_token(token: str) -> str:
        """Return the SHA-256 hash of a token.

        Args:
            token: The plain-text token.

        Returns:
            str: The hex-encoded SHA-256 hash of the token.
        """
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    async def create_reset_token(
        db: AsyncSession,
        user: User,
    ) -> str:
        """Create a new password reset token.

        Generates a token, hashes it, deletes previous unused reset tokens for
        the user, inserts a new PasswordResetToken that expires in 15 minutes,
        commits the transaction, and returns the plain-text token.

        Args:
            db: The database session.
            user: The user requesting the reset.

        Returns:
            str: The plain-text token.
        """
        plain_token = PasswordResetService.generate_token()
        token_hash = PasswordResetService.hash_token(plain_token)

        # Delete previous unused reset tokens for the same user
        await db.execute(
            delete(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            )
        )

        # Insert new PasswordResetToken expiring in 15 minutes
        expires_at = datetime.now(UTC) + timedelta(minutes=15)
        reset_token = PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        db.add(reset_token)
        await db.commit()

        # nosemgrep - logs only user ID and timestamp, no token values
        logger.info(
            "Created password reset token for user ID: %s expiring at %s",
            user.id,
            expires_at,
        )

        return plain_token

    @staticmethod
    async def validate_token(
        db: AsyncSession,
        token: str,
    ) -> PasswordResetToken:
        """Validate a password reset token.

        Hashes the incoming token, checks the database, validates that the token
        exists, is not expired, and has not been used yet.

        Args:
            db: The database session.
            token: The plain-text reset token.

        Returns:
            PasswordResetToken: The validated token model instance with user loaded.

        Raises:
            UnauthorizedException: If the token is invalid, expired, or already used.
        """
        token_hash = PasswordResetService.hash_token(token)
        stmt = (
            select(PasswordResetToken)
            .where(PasswordResetToken.token_hash == token_hash)
            .options(selectinload(PasswordResetToken.user))
        )
        result = await db.execute(stmt)
        db_token = result.scalar_one_or_none()

        if db_token is None:
            logger.warning("Password reset token not found in database.")
            raise UnauthorizedException("Invalid or expired password reset token")

        if db_token.used_at is not None:
            # nosemgrep - logs usage timestamp metadata only, no token values
            logger.warning("Password reset token already used at %s.", db_token.used_at)
            raise UnauthorizedException("Invalid or expired password reset token")

        if db_token.expires_at <= datetime.now(UTC):
            # nosemgrep - logs expiration timestamp metadata only, no token values
            logger.warning("Password reset token expired at %s.", db_token.expires_at)
            raise UnauthorizedException("Invalid or expired password reset token")

        return db_token

    @staticmethod
    async def reset_password(
        db: AsyncSession,
        token: str,
        new_password: str,
    ) -> None:
        """Reset the user's password using the provided reset token.

        Validates the token, loads the user, hashes the new password, updates
        the user's password hash, marks the token as used, and revokes all active
        refresh sessions for the user.

        Args:
            db: The database session.
            token: The plain-text reset token.
            new_password: The new plain-text password.

        Raises:
            UnauthorizedException: If the token is invalid or expired.
        """
        db_token = await PasswordResetService.validate_token(db, token)
        user = db_token.user

        # Hash new password
        hashed = await asyncio.to_thread(hash_password, new_password)
        user.hashed_password = hashed

        # Mark token as used
        db_token.used_at = datetime.now(UTC)

        # Revoke every active refresh session
        await RefreshTokenService.revoke_all_for_user(db, user.id)

        await db.commit()
        # nosemgrep - logs only user ID on reset, no passwords or tokens
        logger.info(
            "Successfully reset password and revoked all sessions for user ID: %s",
            user.id,
        )

    @staticmethod
    async def cleanup_expired_tokens(
        db: AsyncSession,
    ) -> int:
        """Delete all expired or already-used password reset tokens.

        Args:
            db: The database session.

        Returns:
            int: The number of deleted tokens.
        """
        from sqlalchemy.engine import CursorResult

        stmt = delete(PasswordResetToken).where(
            or_(
                PasswordResetToken.expires_at <= datetime.now(UTC),
                PasswordResetToken.used_at.is_not(None),
            )
        )
        result: CursorResult[tuple[()]] = await db.execute(stmt)  # type: ignore[assignment]
        await db.commit()

        deleted_count: int = result.rowcount or 0
        logger.info(
            "Cleaned up %d expired or used password reset tokens", deleted_count
        )
        return deleted_count
