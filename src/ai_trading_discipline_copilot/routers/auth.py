import logging
import uuid
from typing import TYPE_CHECKING, Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Request,
    Response,
    status,
)
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_trading_discipline_copilot.core.config import get_settings
from ai_trading_discipline_copilot.core.dependencies import (
    get_current_user,
    get_db,
)
from ai_trading_discipline_copilot.core.exceptions import (
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)
from ai_trading_discipline_copilot.core.security import decode_refresh_token
from ai_trading_discipline_copilot.models.user import User
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


async def run_cleanup_task() -> None:
    """Background task to clean up expired sessions using a fresh DB session."""
    from ai_trading_discipline_copilot.core.database import AsyncSessionFactory

    async with AsyncSessionFactory() as db:
        await RefreshTokenService.cleanup_expired_sessions(db)


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    user_data: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    """Register a new user."""

    user = await UserService.register_user(db, user_data)
    return UserResponse.model_validate(user)


@router.post(
    "/login",
    response_model=Token,
)
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

    refresh_token = request.cookies.get("refresh_token")
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

    refresh_token = request.cookies.get("refresh_token")
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

    refresh_token = request.cookies.get("refresh_token")
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

    refresh_token = request.cookies.get("refresh_token")
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


@router.post("/test-email", status_code=204)
async def test_email() -> None:
    """Temporary endpoint to verify Resend integration."""

    await EmailService.send_email(
        to="sreenandpk3@gmail.com",
        subject="Resend Test",
        html="<h1>Hello from AI Trading Discipline Copilot 🚀</h1>",
    )


async def send_reset_email_task(email: str, reset_url: str, app_name: str) -> None:
    """Send a password reset email asynchronously in the background.

    Args:
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
        logger.exception("Failed to send password reset email to %s: %s", email, e)


@router.post(
    "/forgot-password",
    response_model=ForgotPasswordResponse,
    status_code=status.HTTP_200_OK,
)
async def forgot_password(
    request_data: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ForgotPasswordResponse:
    """Request a password reset link.

    Generates a password reset token if the email exists, builds a reset link,
    and sends a reset email in the background. Always returns a generic success
    message to prevent account enumeration.
    """
    result = await db.execute(
        select(User).where(User.email == request_data.email)
    )
    user = result.scalar_one_or_none()

    if user:
        plain_token = await PasswordResetService.create_reset_token(db, user)
        reset_url = f"{settings.frontend_url}/reset-password?token={plain_token}"
        background_tasks.add_task(
            send_reset_email_task,
            email=user.email,
            reset_url=reset_url,
            app_name=settings.app_name,
        )

    return ForgotPasswordResponse(
        message=(
            "If an account with that email exists, "
            "a password reset link has been sent."
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
        raise UnauthorizedException(
            "Invalid or expired password reset token"
        ) from err

    return ResetPasswordResponse(
        message="Password reset successful."
    )

