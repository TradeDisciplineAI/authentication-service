"""Email verification service business logic."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ai_trading_discipline_copilot.core.exceptions import UnauthorizedException
from ai_trading_discipline_copilot.models.email_verification_token import (
    EmailVerificationToken,
)

if TYPE_CHECKING:
    from ai_trading_discipline_copilot.models.user import User

logger = logging.getLogger(__name__)


class EmailVerificationService:
    """Business logic for handling email verifications."""

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
    async def create_verification_token(
        db: AsyncSession,
        user: User,
    ) -> str:
        """Create a new email verification token.

        Generates a token, hashes it, deletes previous unused verification tokens
        for the user, inserts a new EmailVerificationToken that expires in 24 hours,
        commits the transaction, and returns the plain-text token.

        Args:
            db: The database session.
            user: The user requesting verification.

        Returns:
            str: The plain-text token.
        """
        plain_token = EmailVerificationService.generate_token()
        token_hash = EmailVerificationService.hash_token(plain_token)

        # Delete previous unused verification tokens for the same user
        await db.execute(
            delete(EmailVerificationToken).where(
                EmailVerificationToken.user_id == user.id,
                EmailVerificationToken.used_at.is_(None),
            )
        )

        # Insert new EmailVerificationToken expiring in 24 hours
        expires_at = datetime.now(UTC) + timedelta(hours=24)
        verification_token = EmailVerificationToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        db.add(verification_token)
        await db.commit()

        logger.info(
            "Created email verification token for user ID: %s expiring at %s",
            user.id,
            expires_at,
        )

        return plain_token

    @staticmethod
    async def validate_token(
        db: AsyncSession,
        token: str,
    ) -> EmailVerificationToken:
        """Validate an email verification token.

        Hashes the incoming token, checks the database, validates that the token
        exists, is not expired, and has not been used yet.

        Args:
            db: The database session.
            token: The plain-text verification token.

        Returns:
            EmailVerificationToken: The validated token model instance with user loaded.

        Raises:
            UnauthorizedException: If the token is invalid, expired, or already used.
        """
        token_hash = EmailVerificationService.hash_token(token)
        stmt = (
            select(EmailVerificationToken)
            .where(EmailVerificationToken.token_hash == token_hash)
            .options(selectinload(EmailVerificationToken.user))
        )
        result = await db.execute(stmt)
        db_token = result.scalar_one_or_none()

        if db_token is None:
            logger.warning("Email verification token not found in database.")
            raise UnauthorizedException("Invalid or expired email verification token")

        if db_token.used_at is not None:
            logger.warning(
                "Email verification token already used at %s.", db_token.used_at
            )
            raise UnauthorizedException("Invalid or expired email verification token")

        if db_token.expires_at <= datetime.now(UTC):
            logger.warning(
                "Email verification token expired at %s.", db_token.expires_at
            )
            raise UnauthorizedException("Invalid or expired email verification token")

        return db_token

    @staticmethod
    async def verify_email(
        db: AsyncSession,
        token: str,
    ) -> User:
        """Verify the user's email using the provided verification token.

        Validates the token, loads the user, sets is_verified=True on the user,
        marks the token as used, and commits.

        Args:
            db: The database session.
            token: The plain-text verification token.

        Returns:
            The verified User object.

        Raises:
            UnauthorizedException: If the token is invalid or expired.
        """
        db_token = await EmailVerificationService.validate_token(db, token)
        user = db_token.user

        # Mark user as verified
        user.is_verified = True

        # Mark token as used
        db_token.used_at = datetime.now(UTC)

        await db.commit()
        logger.info(
            "Successfully verified email for user ID: %s",
            user.id,
        )
        return user

    @staticmethod
    async def cleanup_expired_tokens(
        db: AsyncSession,
    ) -> int:
        """Delete all expired or already-used email verification tokens.

        Args:
            db: The database session.

        Returns:
            int: The number of deleted tokens.
        """
        from sqlalchemy.engine import CursorResult

        stmt = delete(EmailVerificationToken).where(
            or_(
                EmailVerificationToken.expires_at <= datetime.now(UTC),
                EmailVerificationToken.used_at.is_not(None),
            )
        )
        result: CursorResult[tuple[()]] = await db.execute(stmt)  # type: ignore[assignment]
        await db.commit()

        deleted_count: int = result.rowcount or 0
        logger.info(
            "Cleaned up %d expired or used email verification tokens", deleted_count
        )
        return deleted_count
