import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_trading_discipline_copilot.core.config import get_settings
from ai_trading_discipline_copilot.core.exceptions import UnauthorizedException
from ai_trading_discipline_copilot.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_refresh_token,
    verify_refresh_token,
)
from ai_trading_discipline_copilot.models.refresh_token import RefreshToken
from ai_trading_discipline_copilot.models.user import User

settings = get_settings()
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TokenPair:
    access_token: str
    refresh_token: str


class RefreshTokenService:
    """Business logic for refresh token sessions."""

    @staticmethod
    async def create_session(
        db: AsyncSession,
        user: User,
        token_hash: str,
        jti: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_name: str | None = None,
        commit: bool = True,
    ) -> RefreshToken:
        """Create a refresh token session."""

        session = RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            jti=jti,
            ip_address=ip_address,
            user_agent=user_agent,
            device_name=device_name,
            expires_at=datetime.now(UTC)
            + timedelta(days=settings.refresh_token_expire_days),
        )

        db.add(session)
        if commit:
            await db.commit()
            await db.refresh(session)
        else:
            await db.flush()

        return session

    @staticmethod
    async def get_by_jti(
        db: AsyncSession,
        jti: str,
    ) -> RefreshToken | None:
        """Get a refresh token session by JTI."""

        result = await db.execute(
            select(RefreshToken).where(
                RefreshToken.jti == jti,
            )
        )

        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        session_id: uuid.UUID,
    ) -> RefreshToken | None:
        """Get a refresh token session by ID."""

        result = await db.execute(
            select(RefreshToken).where(
                RefreshToken.id == session_id,
            )
        )

        return result.scalar_one_or_none()

    @staticmethod
    async def get_active_sessions_for_user(
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> list[RefreshToken]:
        """Get all active (non-revoked, non-expired) refresh sessions for a user."""

        result = await db.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > datetime.now(UTC),
            )
        )

        return list(result.scalars().all())

    @staticmethod
    async def revoke(
        db: AsyncSession,
        session: RefreshToken,
        commit: bool = True,
    ) -> None:
        """Revoke a refresh token session."""

        session.revoked_at = datetime.now(UTC)
        if commit:
            await db.commit()

    @staticmethod
    async def revoke_all_for_user(
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> None:
        """Revoke all active refresh sessions for a user."""
        from sqlalchemy import update

        await db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        await db.commit()
        logger.info("Revoked all active sessions for user ID: %s", user_id)

    @staticmethod
    async def update_last_used(
        db: AsyncSession,
        session: RefreshToken,
        commit: bool = True,
    ) -> None:
        """Update last-used timestamp."""

        session.last_used_at = datetime.now(UTC)
        if commit:
            await db.commit()

    @staticmethod
    async def cleanup_expired_sessions(
        db: AsyncSession,
    ) -> int:
        """Delete all expired refresh sessions from the database."""
        from sqlalchemy import delete

        stmt = delete(RefreshToken).where(RefreshToken.expires_at <= datetime.now(UTC))
        result = await db.execute(stmt)
        await db.commit()
        deleted_count = result.rowcount
        logger.info("Cleaned up %d expired sessions from database", deleted_count)
        return deleted_count

    @staticmethod
    async def rotate(
        db: AsyncSession,
        refresh_token: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_name: str | None = None,
    ) -> TokenPair:
        """
        Rotate a refresh token.

        Validates the existing refresh token, revokes the old session,
        creates a new session, and returns a new access/refresh token pair.
        """

        payload = decode_refresh_token(refresh_token)

        if payload is None:
            raise UnauthorizedException("Invalid refresh token")

        user_id = payload.get("sub")
        jti = payload.get("jti")

        if user_id is None or jti is None:
            raise UnauthorizedException("Invalid refresh token")

        session = await RefreshTokenService.get_by_jti(
            db=db,
            jti=jti,
        )

        if session is None:
            raise UnauthorizedException("Refresh session not found")

        # ── Refresh Token Reuse Detection ──────────────────────────────────
        if session.revoked_at is not None:
            logger.warning(
                "Potential token reuse attack detected! Revoking all sessions for user %s. Token JTI: %s",  # noqa: E501
                session.user_id,
                jti,
            )
            # Revoke all active sessions for this user to contain the compromise.
            await RefreshTokenService.revoke_all_for_user(
                db=db, user_id=session.user_id
            )
            raise UnauthorizedException(
                "Refresh token has been revoked due to reuse detection"
            )

        if session.expires_at <= datetime.now(UTC):
            raise UnauthorizedException("Refresh token has expired")

        if not verify_refresh_token(
            refresh_token,
            session.token_hash,
        ):
            raise UnauthorizedException("Invalid refresh token")

        result = await db.execute(select(User).where(User.id == session.user_id))

        user = result.scalar_one_or_none()

        if user is None:
            raise UnauthorizedException("User not found")

        if not user.is_active:
            raise UnauthorizedException("User account is disabled")

        access_token, _ = create_access_token(str(user.id))
        new_refresh_token, new_jti = create_refresh_token(str(user.id))

        # Revoke the old session and create a new session in a single database transaction.  # noqa: E501
        await RefreshTokenService.revoke(
            db=db,
            session=session,
            commit=False,
        )

        new_session = await RefreshTokenService.create_session(
            db=db,
            user=user,
            token_hash=hash_refresh_token(new_refresh_token),
            jti=new_jti,
            ip_address=ip_address,
            user_agent=user_agent,
            device_name=device_name,
            commit=False,
        )

        await db.commit()
        await db.refresh(new_session)

        logger.info(
            "Rotated refresh token for user '%s'. Old JTI: %s, New JTI: %s",
            user.username,
            jti,
            new_jti,
        )

        return TokenPair(
            access_token=access_token,
            refresh_token=new_refresh_token,
        )
