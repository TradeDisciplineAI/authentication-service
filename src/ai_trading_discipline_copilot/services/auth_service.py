import asyncio
import logging
import os
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
_DUMMY_HASH_PROD = "$2b$12$eImiTXuWVxfMjpqq8q2f.e8b81G0Yg8MhNnd9pLNmP8Q7dI0s4."
_DUMMY_HASH_TEST = "$2b$04$eImiTXuWVxfMjpqq8q2f.eOUC3.E70c32M5lJm/y1qWfE09sYpT2"


def _is_test_mode() -> bool:
    """Evaluate test mode dynamically at operation time."""
    return (
        str(settings.app_env) == "test" or os.getenv("PYTEST_CURRENT_TEST") is not None
    )


def _get_dummy_hash() -> str:
    """Return fast hash in test environment, full 12-round hash in production."""
    return _DUMMY_HASH_TEST if _is_test_mode() else _DUMMY_HASH_PROD


class AuthService:
    """Business logic for authentication."""

    @staticmethod
    async def _authenticate_user(
        db: AsyncSession,
        username: str,
        password: str,
    ) -> User:
        """Authenticate a user using a username or email and password."""

        # Fetch user without lock to avoid holding DB connections
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

        # Use dummy hash if user/hash missing to prevent timing attacks
        target_hash = (
            user.hashed_password
            if (user is not None and user.hashed_password is not None)
            else _get_dummy_hash()
        )

        # Offload bcrypt verification to background thread WITHOUT DB locks
        password_valid = await asyncio.to_thread(
            verify_password,
            password,
            target_hash,
        )

        if user is None or user.hashed_password is None or not password_valid:
            if user is not None:
                query = select(User).where(User.id == user.id)
                if not _is_test_mode():
                    query = query.with_for_update()
                lock_result = await db.execute(query)
                locked_user = lock_result.scalar_one_or_none()
                if locked_user is not None:
                    locked_user.failed_login_attempts += 1
                    if locked_user.failed_login_attempts >= settings.max_login_attempts:
                        locked_user.lockout_until = datetime.now(UTC) + timedelta(
                            minutes=settings.lockout_duration_minutes
                        )
                        logger.warning(
                            "Account locked for user: '%s' after %d failed attempts",
                            locked_user.username,
                            locked_user.failed_login_attempts,
                        )
                    await db.commit()
            logger.warning("Failed login attempt for username/email: '%s'", username)
            raise UnauthorizedException("Invalid username or password")

        if not user.is_active:
            logger.warning(
                "Blocked login attempt for inactive user: '%s'", user.username
            )
            raise UnauthorizedException("User account is disabled")

        # Successful login — reset failure counters if necessary
        if user.failed_login_attempts > 0 or user.lockout_until is not None:
            query = select(User).where(User.id == user.id)
            if not _is_test_mode():
                query = query.with_for_update()
            lock_result = await db.execute(query)
            locked_user = lock_result.scalar_one_or_none()
            if locked_user is not None:
                locked_user.failed_login_attempts = 0
                locked_user.lockout_until = None
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
                # nosemgrep - logs only JTI (UUID), not the JWT
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

    @staticmethod
    async def login_with_google(
        db: AsyncSession,
        google_id: str,
        email: str,
        response: Response,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_name: str | None = None,
    ) -> Token:
        """Log in or register a user using Google OAuth2 credentials."""

        # 1. Try to find user by google_id
        q1 = select(User).where(User.google_id == google_id)
        if not _is_test_mode():
            q1 = q1.with_for_update()
        result = await db.execute(q1)
        user = result.scalar_one_or_none()

        if user is None:
            # 2. Try to find user by email
            q2 = select(User).where(User.email == email)
            if not _is_test_mode():
                q2 = q2.with_for_update()
            result = await db.execute(q2)
            user = result.scalar_one_or_none()

            if user is not None:
                # Validate is_active before linking
                if not user.is_active:
                    logger.warning(
                        "Blocked Google login attempt for inactive user "
                        "(before link): '%s'",
                        user.username,
                    )
                    raise ForbiddenException("User account is disabled")

                # Link Google account to existing user
                user.google_id = google_id
                # Google email is trusted and verified
                user.is_verified = True
                await db.commit()
                logger.info("Linked Google ID to existing user email: '%s'", email)
            else:
                # 3. Register a new user
                # Create a clean username from email
                base_username = email.split("@")[0][:40]
                base_username = "".join(
                    c for c in base_username if c.isalnum() or c in ("_", "-")
                )
                if not base_username:
                    base_username = "google_user"
                username = base_username

                # Ensure username uniqueness
                suffix = 1
                while True:
                    dup_result = await db.execute(
                        select(User).where(User.username == username)
                    )
                    if dup_result.scalar_one_or_none() is None:
                        break
                    username = f"{base_username[:35]}_{suffix}"
                    suffix += 1

                user = User(
                    username=username,
                    email=email,
                    google_id=google_id,
                    hashed_password=None,  # No local password
                    is_verified=True,  # Google is verified
                )
                db.add(user)
                await db.commit()
                await db.refresh(user)
                logger.info("Registered new user '%s' via Google OAuth2", username)

        # Check account status (e.g. is_active)
        if not user.is_active:
            logger.warning(
                "Blocked Google login attempt for inactive user: '%s'",
                user.username,
            )
            raise ForbiddenException("User account is disabled")

        # Successful login — reset lockout counter
        if user.failed_login_attempts > 0:
            user.failed_login_attempts = 0
            user.lockout_until = None
            await db.commit()

        # Issue tokens
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
            "User '%s' logged in successfully via Google. IP: %s, Device: %s",
            user.username,
            ip_address,
            device_name,
        )

        return Token(
            access_token=access_token,
        )
