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
from sqlalchemy.ext.asyncio import AsyncSession

from ai_trading_discipline_copilot.core.config import get_settings
from ai_trading_discipline_copilot.core.dependencies import (
    get_current_user,
    get_db,
)
from ai_trading_discipline_copilot.core.exceptions import (
    NotFoundException,
    UnauthorizedException,
)
from ai_trading_discipline_copilot.core.security import decode_refresh_token
from ai_trading_discipline_copilot.schemas.user import (
    Token,
    UserCreate,
    UserResponse,
    UserSessionResponse,
)
from ai_trading_discipline_copilot.services.auth_service import AuthService
from ai_trading_discipline_copilot.services.refresh_token_service import (
    RefreshTokenService,
)
from ai_trading_discipline_copilot.services.user_service import UserService

if TYPE_CHECKING:
    from ai_trading_discipline_copilot.models.user import User

settings = get_settings()

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

    refresh_token = request.cookies.get(settings.cookie_name)
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
    """Log out the current session by revoking the refresh token
    and deleting the cookie.
    """

    refresh_token = request.cookies.get(settings.cookie_name)
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

    refresh_token = request.cookies.get(settings.cookie_name)
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

    refresh_token = request.cookies.get(settings.cookie_name)
    session = await RefreshTokenService.get_by_id(db=db, session_id=session_id)
    if not session or session.user_id != current_user.id:
        raise NotFoundException("Session not found")

    await RefreshTokenService.revoke(db=db, session=session)

    # If the user is revoking their current session, clear their cookie
    if refresh_token:
        payload = decode_refresh_token(refresh_token)
        if payload and payload.get("jti") == session.jti:
            AuthService.delete_refresh_cookie(response)
