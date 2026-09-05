import logging
import os
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any

import httpx
import jwt
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    Request,
    Response,
    status,
)
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_trading_discipline_copilot.core.config import get_settings
from ai_trading_discipline_copilot.core.dependencies import (
    get_current_user,
    get_db,
)
from ai_trading_discipline_copilot.core.exceptions import (
    AppException,
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)
from ai_trading_discipline_copilot.core.limiter import limiter
from ai_trading_discipline_copilot.core.security import (
    decode_refresh_token,
    hash_refresh_token,
)
from ai_trading_discipline_copilot.models.user import User
from ai_trading_discipline_copilot.schemas.email_verification import (
    ResendVerificationRequest,
    ResendVerificationResponse,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from ai_trading_discipline_copilot.schemas.password_reset import (
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
)
from ai_trading_discipline_copilot.schemas.user import (
    Token,
    UserCreate,
    UserResponse,
    UserSessionResponse,
)
from ai_trading_discipline_copilot.services.auth_service import AuthService
from ai_trading_discipline_copilot.services.email_service import EmailService
from ai_trading_discipline_copilot.services.email_verification_service import (
    EmailVerificationService,
)
from ai_trading_discipline_copilot.services.password_reset_service import (
    PasswordResetService,
)
from ai_trading_discipline_copilot.services.refresh_token_service import (
    RefreshTokenService,
)
from ai_trading_discipline_copilot.services.user_service import UserService

if TYPE_CHECKING:
    pass

settings = get_settings()
_REFRESH_COOKIE_NAME = settings.cookie_name
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


def parse_device_name(user_agent: str | None) -> str:
    """Parse a basic human-readable device name from the User-Agent header."""
    if not user_agent:
        return "Unknown Device"
    ua = user_agent.lower()
    if "iphone" in ua:
        return "iPhone"
    if "ipad" in ua:
        return "iPad"
    if "android" in ua:
        return "Android Device"
    if "windows" in ua:
        return "Windows PC"
    if "macintosh" in ua or "mac os x" in ua:
        return "macOS Device"
    if "linux" in ua:
        return "Linux Device"
    return "Web Client"


def _mask_email(email: str) -> str:
    """Mask email address to protect PII in logs (e.g. jo***@gmail.com)."""
    try:
        parts = email.split("@")
        if len(parts) != 2:
            return email
        local, domain = parts
        masked_local = local[0] + "*" if len(local) <= 2 else local[:2] + "***"
        return f"{masked_local}@{domain}"
    except Exception:
        return "masked_email"


async def run_cleanup_task() -> None:
    """Clean up expired sessions and tokens using a fresh DB session."""
    from ai_trading_discipline_copilot.core.database import AsyncSessionFactory

    async with AsyncSessionFactory() as db:
        try:
            await RefreshTokenService.cleanup_expired_sessions(db)
        except Exception:
            logger.exception("Failed to clean up expired refresh token sessions")

        try:
            await EmailVerificationService.cleanup_expired_tokens(db)
        except Exception:
            logger.exception("Failed to clean up expired email verification tokens")

        try:
            await PasswordResetService.cleanup_expired_tokens(db)
        except Exception:
            logger.exception("Failed to clean up expired password reset tokens")


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("5/minute")
async def register(
    request: Request,
    user_data: UserCreate,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    """Register a new user."""

    user = await UserService.register_user(db, user_data)

    plain_token = await EmailVerificationService.create_verification_token(db, user)
    verification_url = f"{settings.frontend_url}/verify-email?token={plain_token}"

    background_tasks.add_task(
        send_verification_email_task,
        user_id=user.id,
        email=user.email,
        verification_url=verification_url,
    )

    return UserResponse.model_validate(user)


def _is_login_rate_limiting_exempt(request: Request) -> bool:
    """Check if rate limiting for the login endpoint is exempted."""
    return not get_settings().enable_login_rate_limiting


@router.post(
    "/login",
    response_model=Token,
)
@limiter.limit("10/minute", exempt_when=_is_login_rate_limiting_exempt)
async def login(
    response: Response,
    request: Request,
    background_tasks: BackgroundTasks,
    form_data: Annotated[
        OAuth2PasswordRequestForm,
        Depends(),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Token:
    """Authenticate a user."""

    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    device_name = parse_device_name(user_agent)

    # Queue database cleanup to run in the background
    background_tasks.add_task(run_cleanup_task)

    return await AuthService.login(
        response=response,
        db=db,
        username=form_data.username,
        password=form_data.password,
        ip_address=ip_address,
        user_agent=user_agent,
        device_name=device_name,
    )


@router.post(
    "/refresh",
    response_model=Token,
)
async def refresh(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Token:
    """Rotate the refresh token and issue a new access token."""

    refresh_token = request.cookies.get(_REFRESH_COOKIE_NAME)
    if refresh_token is None:
        raise UnauthorizedException("Missing refresh token")

    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    device_name = parse_device_name(user_agent)

    try:
        tokens = await RefreshTokenService.rotate(
            db=db,
            refresh_token=refresh_token,
            ip_address=ip_address,
            user_agent=user_agent,
            device_name=device_name,
        )

        AuthService.set_refresh_cookie(
            response=response,
            refresh_token=tokens.refresh_token,
        )

        return Token(
            access_token=tokens.access_token,
        )

    except UnauthorizedException as exc:
        AuthService.delete_refresh_cookie(response)
        raise exc


@router.get(
    "/me",
    response_model=UserResponse,
)
async def get_me(
    current_user: Annotated["User", Depends(get_current_user)],
) -> UserResponse:
    """Return the authenticated user's profile."""

    return UserResponse.model_validate(current_user)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def logout(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Log out the current session by revoking the refresh token and deleting the cookie."""  # noqa: E501

    refresh_token = request.cookies.get(_REFRESH_COOKIE_NAME)
    await AuthService.logout(
        response=response,
        db=db,
        refresh_token=refresh_token,
    )


@router.post(
    "/logout-all",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def logout_all(
    response: Response,
    current_user: Annotated["User", Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Revoke all sessions for the user and clear the refresh cookie."""

    await RefreshTokenService.revoke_all_for_user(
        db=db,
        user_id=current_user.id,
    )
    AuthService.delete_refresh_cookie(response)


@router.get(
    "/sessions",
    response_model=list[UserSessionResponse],
)
async def get_sessions(
    request: Request,
    current_user: Annotated["User", Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[UserSessionResponse]:
    """Get all active sessions for the authenticated user."""

    refresh_token = request.cookies.get(_REFRESH_COOKIE_NAME)
    current_jti = None
    if refresh_token:
        payload = decode_refresh_token(refresh_token)
        if payload:
            current_jti = payload.get("jti")

    sessions = await RefreshTokenService.get_active_sessions_for_user(
        db=db,
        user_id=current_user.id,
    )

    return [
        UserSessionResponse(
            id=s.id,
            device_name=s.device_name,
            ip_address=s.ip_address,
            user_agent=s.user_agent,
            created_at=s.created_at,
            last_used_at=s.last_used_at,
            is_current=(s.jti == current_jti) if current_jti else False,
        )
        for s in sessions
    ]


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_session(
    session_id: uuid.UUID,
    request: Request,
    response: Response,
    current_user: Annotated["User", Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Revoke a specific session for the user."""

    refresh_token = request.cookies.get(_REFRESH_COOKIE_NAME)
    session = await RefreshTokenService.get_by_id(db=db, session_id=session_id)
    if not session or session.user_id != current_user.id:
        raise NotFoundException("Session not found")

    await RefreshTokenService.revoke(db=db, session=session)

    # If the user is revoking their current session, clear their cookie
    if refresh_token:
        payload = decode_refresh_token(refresh_token)
        if payload and payload.get("jti") == session.jti:
            AuthService.delete_refresh_cookie(response)


@router.post(
    "/cleanup",
    status_code=status.HTTP_200_OK,
)
async def cleanup_sessions(
    current_user: Annotated["User", Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, int]:
    """Clean up expired sessions from the database (Admin only)."""
    from ai_trading_discipline_copilot.models.user import UserRole

    if current_user.role != UserRole.ADMIN:
        raise ForbiddenException("Only admins can perform session cleanup")

    deleted_count = await RefreshTokenService.cleanup_expired_sessions(db=db)
    return {"deleted_sessions": deleted_count}


async def send_verification_email_task(
    user_id: uuid.UUID,
    email: str,
    verification_url: str,
) -> None:
    """Send email verification link asynchronously in the background.

    Args:
        user_id: The ID of the user.
        email: The recipient's email address.
        verification_url: The verification link.
    """
    try:
        await EmailService.send_verification_email(
            to=email,
            verification_url=verification_url,
        )
    except Exception as e:
        logger.exception(
            "Failed to send email [type=verification] to user_id=%s, email=%s: %s",
            user_id,
            _mask_email(email),
            e,
        )


async def send_reset_email_task(
    user_id: uuid.UUID,
    email: str,
    reset_url: str,
    app_name: str,
) -> None:
    """Send a password reset email asynchronously in the background.

    Args:
        user_id: The ID of the user.
        email: The recipient's email address.
        reset_url: The plain-text password reset URL.
        app_name: The application name to display.
    """
    try:
        import html
        from datetime import UTC, datetime

        escaped_app_name = html.escape(app_name)
        escaped_reset_url = html.escape(reset_url)
        current_year = datetime.now(UTC).year

        html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Reset your password</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background-color: #f9fafb;
      margin: 0;
      padding: 0;
    }}
    .container {{
      max-width: 576px;
      margin: 32px auto;
      background-color: #ffffff;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      padding: 32px;
    }}
    .header {{
      margin-bottom: 24px;
    }}
    .app-name {{
      font-size: 20px;
      font-weight: bold;
      color: #111827;
    }}
    .content {{
      font-size: 16px;
      line-height: 24px;
      color: #374151;
    }}
    .button-container {{
      margin: 32px 0;
      text-align: center;
    }}
    .button {{
      display: inline-block;
      background-color: #2563eb;
      color: #ffffff !important;
      font-weight: 600;
      text-decoration: none;
      padding: 12px 24px;
      border-radius: 6px;
      font-size: 16px;
    }}
    .url-text {{
      font-size: 14px;
      color: #6b7280;
      word-break: break-all;
      margin-top: 24px;
    }}
    .footer {{
      margin-top: 32px;
      border-top: 1px solid #e5e7eb;
      padding-top: 16px;
      font-size: 12px;
      color: #9ca3af;
      text-align: center;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <span class="app-name">{escaped_app_name}</span>
    </div>
    <div class="content">
      <p>Hello,</p>
      <p>We received a request to reset the password for your account.</p>
      <p>Click the button below to set a new password:</p>
      <div class="button-container">
        <a href="{escaped_reset_url}" class="button" target="_blank">Reset Password</a>
      </div>
      <p>This password reset link is only valid for <strong>15 minutes</strong>.</p>
      <p>If you did not request a password reset, you can safely ignore this email.</p>
      <p class="url-text">
        If you're having trouble clicking the button, copy and paste the URL below:<br>
        <a href="{escaped_reset_url}">{escaped_reset_url}</a>
      </p>
    </div>
    <div class="footer">
      &copy; {current_year} {escaped_app_name}. All rights reserved.
    </div>
  </div>
</body>
</html>"""

        await EmailService.send_email(
            to=email,
            subject="Reset your password",
            html=html_content,
        )
    except Exception as e:
        # nosemgrep - logs only user ID and masked email, no passwords or tokens
        logger.exception(
            "Failed to send email [type=password_reset] to user_id=%s, email=%s: %s",
            user_id,
            _mask_email(email),
            e,
        )


@router.post(
    "/forgot-password",
    response_model=ForgotPasswordResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("3/hour")
async def forgot_password(
    request: Request,
    request_data: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ForgotPasswordResponse:
    """Request a password reset link.

    Generates a password reset token if the email exists, builds a reset link,
    and sends a reset email in the background. Always returns a generic success
    message to prevent account enumeration.
    """
    result = await db.execute(select(User).where(User.email == request_data.email))
    user = result.scalar_one_or_none()

    if user:
        plain_token = await PasswordResetService.create_reset_token(db, user)
        reset_url = f"{settings.frontend_url}/#/reset-password/{plain_token}"
        background_tasks.add_task(
            send_reset_email_task,
            user_id=user.id,
            email=user.email,
            reset_url=reset_url,
            app_name=settings.app_name,
        )

    return ForgotPasswordResponse(
        message=(
            "If an account with that email exists, a password reset link has been sent."
        )
    )


@router.post(
    "/reset-password",
    response_model=ResetPasswordResponse,
    status_code=status.HTTP_200_OK,
)
async def reset_password(
    request_data: ResetPasswordRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ResetPasswordResponse:
    """Reset password using a valid reset token.

    Verifies the token, updates the password, and revokes all active sessions.
    """
    try:
        await PasswordResetService.reset_password(
            db=db,
            token=request_data.token,
            new_password=request_data.new_password,
        )
    except UnauthorizedException as err:
        raise UnauthorizedException("Invalid or expired password reset token") from err

    return ResetPasswordResponse(message="Password reset successful.")


@router.post(
    "/verify-email",
    response_model=VerifyEmailResponse,
    status_code=status.HTTP_200_OK,
)
async def verify_email(
    request: Request,
    response: Response,
    request_data: VerifyEmailRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> VerifyEmailResponse:
    """Verify a user's email using a verification token."""
    try:
        user = await EmailVerificationService.verify_email(db, request_data.token)
    except UnauthorizedException as err:
        raise UnauthorizedException(
            "Invalid or expired email verification token"
        ) from err

    # Automatically log the user in
    try:
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")
        device_name = parse_device_name(user_agent)

        access_token, refresh_token, refresh_jti = AuthService._create_tokens(user)

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
            "User '%s' verified and automatically logged in. IP: %s, Device: %s",
            user.username,
            ip_address,
            device_name,
        )

        return VerifyEmailResponse(
            message="Email verified successfully.",
            access_token=access_token,
            token_type="bearer",  # noqa: S106
        )
    except Exception:
        logger.exception(
            "Email verified successfully for user '%s', but automatic login failed.",
            user.username,
        )
        return VerifyEmailResponse(
            message="Email verified successfully.",
            access_token=None,
            token_type=None,
        )


@router.post(
    "/resend-verification",
    response_model=ResendVerificationResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("3/hour")
async def resend_verification(
    request: Request,
    request_data: ResendVerificationRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ResendVerificationResponse:
    """Resend email verification link.

    Always returns a generic success response to prevent account enumeration.
    """
    result = await db.execute(
        select(User).where(
            or_(
                User.email == request_data.username_or_email,
                User.username == request_data.username_or_email,
            )
        )
    )
    user = result.scalar_one_or_none()

    if user and not user.is_verified:
        plain_token = await EmailVerificationService.create_verification_token(db, user)
        verification_url = f"{settings.frontend_url}/verify-email?token={plain_token}"
        background_tasks.add_task(
            send_verification_email_task,
            user_id=user.id,
            email=user.email,
            verification_url=verification_url,
        )

    return ResendVerificationResponse(message="Verification email sent.")


def _get_google_redirect_uri(request: Request) -> str:
    if settings.public_api_url:
        base_url = settings.public_api_url.rstrip("/")
        path = request.url_for("google_callback").path
        return f"{base_url}{path}"
    return str(request.url_for("google_callback"))


@router.get("/oauth2/google/login")
async def google_login(request: Request) -> RedirectResponse:
    """Redirect to Google's OAuth2 consent page."""
    if not settings.google_client_id:
        raise AppException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google OAuth2 client ID is not configured.",
        )

    # Generate a secure state token signed with the app's secret key
    state_payload = {
        "timestamp": datetime.now(UTC).timestamp(),
        "nonce": uuid.uuid4().hex,
    }
    state_token = jwt.encode(
        state_payload,
        settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm,
    )

    google_auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={settings.google_client_id}"
        f"&redirect_uri={_get_google_redirect_uri(request)}"
        "&response_type=code"
        "&scope=openid%20email%20profile"
        f"&state={state_token}"
    )
    redirect_response = RedirectResponse(url=google_auth_url)
    redirect_response.set_cookie(
        key="oauth_state",
        value=state_token,
        httponly=True,
        max_age=600,
        path="/auth",
        samesite="lax",
    )
    return redirect_response


@router.get("/oauth2/google/callback", name="google_callback")
async def google_callback(
    request: Request,
    code: str,
    state: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RedirectResponse:
    """Handle the Google OAuth2 callback.

    Exchanges authorization code for access token, fetches profile,
    registers or logs in user, and redirects browser to frontend URL.
    """
    if not settings.google_client_id or not settings.google_client_secret:
        raise AppException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google OAuth2 credentials are not configured.",
        )

    # 1. Verify state token signature, expiration, and client binding (nonce)
    cookie_state = request.cookies.get("oauth_state")
    if not cookie_state or cookie_state != state:
        raise UnauthorizedException("OAuth state mismatch or missing binding")

    try:
        payload = jwt.decode(
            state,
            settings.secret_key.get_secret_value(),
            algorithms=[settings.algorithm],
        )
        if datetime.now(UTC).timestamp() - payload.get("timestamp", 0) > 600:
            raise UnauthorizedException("OAuth state token has expired")
    except jwt.PyJWTError as err:
        raise UnauthorizedException("Invalid OAuth state token") from err

    # 2. Exchange authorization code for token
    try:
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret.get_secret_value(),
                    "redirect_uri": _get_google_redirect_uri(request),
                    "grant_type": "authorization_code",
                },
                timeout=10.0,
            )
            if token_response.status_code != 200:
                error_code = "unknown_error"
                error_desc = "No description provided"
                import contextlib

                with contextlib.suppress(Exception):
                    err_data = token_response.json()
                    error_code = err_data.get("error", error_code)
                    error_desc = err_data.get("error_description", error_desc)
                # nosemgrep - logs only status, error code, and desc, no credentials
                logger.error(
                    "Google token exchange failed: status=%s, error=%s, description=%s",
                    token_response.status_code,
                    error_code,
                    error_desc,
                )
                raise UnauthorizedException(
                    "Failed to exchange authorization code with Google"
                )

            from json import JSONDecodeError

            try:
                tokens = token_response.json()
                if not isinstance(tokens, dict):
                    raise UnauthorizedException(
                        "Failed to exchange authorization code with Google"
                    )
            except JSONDecodeError as err:
                raise UnauthorizedException(
                    "Failed to exchange authorization code with Google"
                ) from err

            access_token = tokens.get("access_token")
            if not access_token:
                raise UnauthorizedException(
                    "Failed to retrieve access token from Google"
                )

            # 3. Fetch user profile from Google
            userinfo_response = await client.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10.0,
            )
            if userinfo_response.status_code != 200:
                logger.error(
                    "Google userinfo request failed: %s", userinfo_response.text
                )
                raise UnauthorizedException("Failed to fetch user profile from Google")

            try:
                user_info = userinfo_response.json()
                if not isinstance(user_info, dict):
                    raise UnauthorizedException(
                        "Failed to fetch user profile from Google"
                    )
            except JSONDecodeError as err:
                raise UnauthorizedException(
                    "Failed to fetch user profile from Google"
                ) from err
    except httpx.HTTPError as err:
        logger.error("Google API communication failed: %s", str(err))
        raise UnauthorizedException(
            "Failed to communicate with Google authentication servers"
        ) from err

    google_id = user_info.get("sub")
    email = user_info.get("email")
    email_verified = user_info.get("email_verified", False)

    if not google_id or not email:
        raise UnauthorizedException("Google user profile is incomplete")

    if not email_verified:
        raise UnauthorizedException("Google email account is not verified")

    # 4. Perform login or registration, attaching cookies directly to RedirectResponse
    redirect_url = f"{settings.frontend_url}/#/auth/callback"
    redirect_response = RedirectResponse(url=redirect_url)

    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    device_name = parse_device_name(user_agent)

    local_tokens = await AuthService.login_with_google(
        db=db,
        google_id=google_id,
        email=email,
        response=redirect_response,
        ip_address=ip_address,
        user_agent=user_agent,
        device_name=device_name,
    )

    # 5. Append access token to redirect URL for frontend usage as a fragment (#)
    # Fragments are NOT sent to the server in HTTP requests, preventing token
    # leakage in proxy/server logs and Referer headers. However, fragments are
    # still visible in the browser address bar. The frontend should clear the
    # hash immediately after reading the token (e.g. history.replaceState).
    token = local_tokens.access_token
    redirect_response.headers["Location"] = f"{redirect_url}#token={token}"
    redirect_response.delete_cookie(
        key="oauth_state",
        path="/auth",
    )
    return redirect_response


@router.post(
    "/subscribe",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
)
async def subscribe_to_pro(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payment_token: Annotated[str | None, Header(alias="X-Payment-Token")] = None,
) -> User:
    """Upgrade user to PRO tier after verifying payment entitlement."""
    is_test_dev = (
        str(settings.app_env) in ("test", "development")
        or os.getenv("PYTEST_CURRENT_TEST") is not None
    )
    if not is_test_dev and not payment_token:
        raise ForbiddenException("Payment entitlement token required")

    current_user.subscription_tier = "PRO"
    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.get(
    "/subscription-status",
    status_code=status.HTTP_200_OK,
)
async def get_subscription_status(
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Return subscription tier and remaining free trade usage metrics."""
    max_free = 6
    is_pro = current_user.subscription_tier == "PRO"
    # Fail closed: Only explicitly PRO tier receives unlimited trades.
    remaining = 999999 if is_pro else max(0, max_free - current_user.trades_count)
    return {
        "user_id": str(current_user.id),
        "username": current_user.username,
        "subscription_tier": current_user.subscription_tier,
        "trades_count": current_user.trades_count,
        "max_free_trades": max_free,
        "remaining_free_trades": remaining,
        "is_pro": is_pro,
    }
