import logging
from datetime import UTC, datetime, timedelta

from fastapi import Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_trading_discipline_copilot.core.config import get_settings
from ai_trading_discipline_copilot.core.exceptions import (
    ForbiddenException,
    UnauthorizedException,
)
from ai_trading_discipline_copilot.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_refresh_token,
    verify_password,
)
from ai_trading_discipline_copilot.models.user import User
from ai_trading_discipline_copilot.schemas.user import Token
from ai_trading_discipline_copilot.services.refresh_token_service import (
    RefreshTokenService,
)

settings = get_settings()
logger = logging.getLogger(__name__)

_REFRESH_COOKIE_NAME = settings.cookie_name


class AuthService:
    """Business logic for authentication."""

    @staticmethod
    async def _authenticate_user(
        db: AsyncSession,
        username: str,
        password: str,
    ) -> User:
        """Authenticate a user using a username or email and password."""

        result = await db.execute(
            select(User).where(
                or_(
                    User.username == username,
                    User.email == username,
                )
            )
        )

        user = result.scalar_one_or_none()

        # Check account lockout before any password verification
        if user is not None and user.lockout_until is not None:
            if user.lockout_until > datetime.now(UTC):
                logger.warning(
                    "Blocked login attempt for locked account: '%s'", user.username
                )
                raise UnauthorizedException(
                    "Account is temporarily locked due to too many failed login "
                    "attempts. Please try again later."
                )
            else:
                # Lockout has expired — reset the counter
                user.failed_login_attempts = 0
                user.lockout_until = None
                await db.commit()

        if user is None or not verify_password(
            password,
            user.hashed_password,
        ):
            if user is not None:
                user.failed_login_attempts += 1
                if user.failed_login_attempts >= settings.max_login_attempts:
                    user.lockout_until = datetime.now(UTC) + timedelta(
                        minutes=settings.lockout_duration_minutes
                    )
                    logger.warning(
                        "Account locked for user: '%s' after %d failed attempts",
                        user.username,
                        user.failed_login_attempts,
                    )
                await db.commit()
            logger.warning("Failed login attempt for username/email: '%s'", username)
            raise UnauthorizedException("Invalid username or password")

        if not user.is_active:
            logger.warning(
                "Blocked login attempt for inactive user: '%s'", user.username
            )
            raise UnauthorizedException("User account is disabled")

        # Successful login — reset failure counters
        if user.failed_login_attempts > 0:
            user.failed_login_attempts = 0
            user.lockout_until = None
            await db.commit()

        return user

    @staticmethod
    def _create_tokens(
        user: User,
    ) -> tuple[str, str, str]:
        """Create access and refresh JWTs."""

        access_token, _ = create_access_token(str(user.id))
        refresh_token, refresh_jti = create_refresh_token(str(user.id))

        return (
            access_token,
            refresh_token,
            refresh_jti,
        )

    @staticmethod
    def set_refresh_cookie(
        response: Response,
        refresh_token: str,
    ) -> None:
        """Store the refresh token in an HTTP-only cookie."""

        expires = datetime.now(UTC) + timedelta(
            days=settings.refresh_token_expire_days,
        )

        response.set_cookie(
            key=_REFRESH_COOKIE_NAME,
            value=refresh_token,
            httponly=True,
            secure=settings.cookie_secure,
            samesite=settings.cookie_samesite,
            domain=settings.cookie_domain,
            max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
            expires=expires,
            path=settings.cookie_path,
        )

    @staticmethod
    def delete_refresh_cookie(
        response: Response,
    ) -> None:
        """Delete the refresh token HttpOnly cookie."""

        response.delete_cookie(
            key=_REFRESH_COOKIE_NAME,
            path=settings.cookie_path,
            domain=settings.cookie_domain,
        )

    @staticmethod
    async def login(
        response: Response,
        db: AsyncSession,
        username: str,
        password: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_name: str | None = None,
    ) -> Token:
        """Authenticate a user, create a refresh session, and issue JWTs."""

        user = await AuthService._authenticate_user(
            db=db,
            username=username,
            password=password,
        )

        if not user.is_verified:
            logger.warning(
                "Blocked login attempt for unverified user: '%s'", user.username
            )
            raise ForbiddenException("Please verify your email before logging in.")

        access_token, refresh_token, refresh_jti = AuthService._create_tokens(
            user,
        )

        await RefreshTokenService.create_session(
            db=db,
            user=user,
            token_hash=hash_refresh_token(refresh_token),
            jti=refresh_jti,
            ip_address=ip_address,
            user_agent=user_agent,
            device_name=device_name,
        )

        AuthService.set_refresh_cookie(
            response=response,
            refresh_token=refresh_token,
        )

        logger.info(
            "User '%s' (ID: %s) logged in successfully. IP: %s, Device: %s",
            user.username,
            user.id,
            ip_address,
            device_name,
        )

        return Token(
            access_token=access_token,
        )

    @staticmethod
    async def logout(
        response: Response,
        db: AsyncSession,
        refresh_token: str | None,
    ) -> None:
        """Log out the current session by revoking the refresh token session."""

        if refresh_token is None:
            raise UnauthorizedException("Missing refresh token")

        payload = decode_refresh_token(refresh_token)
        if payload is None:
            AuthService.delete_refresh_cookie(response)
            raise UnauthorizedException("Invalid refresh token")

        jti = payload.get("jti")
        if jti is None:
            AuthService.delete_refresh_cookie(response)
            raise UnauthorizedException("Invalid refresh token")

        session = await RefreshTokenService.get_by_jti(db=db, jti=jti)
        if session:
            if session.revoked_at is not None:
                logger.warning(
                    "Logout attempted with already revoked token JTI: %s", jti
                )
            else:
                await RefreshTokenService.revoke(db=db, session=session)
                logger.info(
                    "Successfully revoked session JTI: %s for user ID: %s on logout",
                    jti,
                    session.user_id,
                )

        AuthService.delete_refresh_cookie(response)
