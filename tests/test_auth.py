from datetime import UTC, datetime, timedelta
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_trading_discipline_copilot.core.security import hash_password
from ai_trading_discipline_copilot.models.refresh_token import RefreshToken
from ai_trading_discipline_copilot.models.user import User, UserRole


@pytest.mark.anyio
async def test_register_success(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test successful user registration."""
    payload = {
        "username": "testuser",
        "email": "testuser@example.com",
        "password": "strongpassword123",
    }
    response = await client.post("/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["username"] == "testuser"
    assert data["email"] == "testuser@example.com"
    assert "id" in data

    # Verify user exists in DB
    result = await db_session.execute(select(User).where(User.username == "testuser"))
    user = result.scalar_one_or_none()
    assert user is not None
    assert user.email == "testuser@example.com"


@pytest.mark.anyio
async def test_register_duplicate_username(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test registration fails with duplicate username."""
    # Pre-insert user
    user = User(
        username="duplicate",
        email="first@example.com",
        hashed_password=hash_password("password"),
    )
    db_session.add(user)
    await db_session.commit()

    payload = {
        "username": "duplicate",
        "email": "second@example.com",
        "password": "password",
    }
    response = await client.post("/auth/register", json=payload)
    assert response.status_code == 409
    assert response.json()["detail"] == "Username already exists"


@pytest.mark.anyio
async def test_register_duplicate_email(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test registration fails with duplicate email."""
    # Pre-insert user
    user = User(
        username="first",
        email="duplicate@example.com",
        hashed_password=hash_password("password"),
    )
    db_session.add(user)
    await db_session.commit()

    payload = {
        "username": "second",
        "email": "duplicate@example.com",
        "password": "password",
    }
    response = await client.post("/auth/register", json=payload)
    assert response.status_code == 409
    assert response.json()["detail"] == "Email already exists"


@pytest.mark.anyio
async def test_login_success(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test successful login returns access token and sets cookie."""
    user = User(
        username="loginuser",
        email="login@example.com",
        hashed_password=hash_password("correctpassword"),
    )
    db_session.add(user)
    await db_session.commit()

    response = await client.post(
        "/auth/login",
        data={"username": "loginuser", "password": "correctpassword"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

    # Verify HttpOnly refresh token cookie
    assert "refresh_token" in response.cookies
    assert response.cookies["refresh_token"] is not None


@pytest.mark.anyio
async def test_login_invalid_credentials(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test login fails with invalid credentials."""
    user = User(
        username="loginuser",
        email="login@example.com",
        hashed_password=hash_password("correctpassword"),
    )
    db_session.add(user)
    await db_session.commit()

    response = await client.post(
        "/auth/login",
        data={"username": "loginuser", "password": "wrongpassword"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password"


@pytest.mark.anyio
async def test_login_inactive_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test login fails if user is disabled (inactive)."""
    user = User(
        username="inactiveuser",
        email="inactive@example.com",
        hashed_password=hash_password("password"),
        is_active=False,
    )
    db_session.add(user)
    await db_session.commit()

    response = await client.post(
        "/auth/login",
        data={"username": "inactiveuser", "password": "password"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "User account is disabled"


@pytest.mark.anyio
async def test_refresh_token_rotation(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test refresh token rotation produces new tokens and revokes old session."""
    user = User(
        username="rotateuser",
        email="rotate@example.com",
        hashed_password=hash_password("password"),
    )
    db_session.add(user)
    await db_session.commit()

    # Login to establish first session
    login_response = await client.post(
        "/auth/login",
        data={"username": "rotateuser", "password": "password"},
    )
    assert login_response.status_code == 200
    first_refresh_token = login_response.cookies["refresh_token"]

    # Rotate token
    client.cookies.set("refresh_token", first_refresh_token)
    refresh_response = await client.post("/auth/refresh")
    assert refresh_response.status_code == 200
    assert "access_token" in refresh_response.json()
    assert "refresh_token" in refresh_response.cookies
    second_refresh_token = refresh_response.cookies["refresh_token"]
    assert first_refresh_token != second_refresh_token


@pytest.mark.anyio
async def test_refresh_token_reuse_detection(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test presenting a revoked token triggers reuse flow (revokes all active sessions)."""
    user = User(
        username="reuseuser",
        email="reuse@example.com",
        hashed_password=hash_password("password"),
    )
    db_session.add(user)
    await db_session.commit()
    user_id = user.id

    # 1. Establish Session A
    client.cookies.clear()
    login_res = await client.post(
        "/auth/login",
        data={"username": "reuseuser", "password": "password"},
    )
    token_a = login_res.cookies["refresh_token"]

    # 2. Establish Session B (log in again to get a second active session)
    client.cookies.clear()
    login_res2 = await client.post(
        "/auth/login",
        data={"username": "reuseuser", "password": "password"},
    )
    token_b = login_res2.cookies["refresh_token"]

    # Verify we have two active sessions in the database
    result = await db_session.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
        )
    )
    active_sessions = result.scalars().all()
    assert len(active_sessions) == 2

    # 3. Rotate Session A
    client.cookies.clear()
    client.cookies.set("refresh_token", token_a)
    rotate_res = await client.post("/auth/refresh")
    assert rotate_res.status_code == 200

    # 4. Present Session A again (Reuse Detection!)
    response = await client.post("/auth/refresh")
    assert response.status_code == 401
    assert "revoked due to reuse detection" in response.json()["detail"].lower()

    # Verify cookie was cleared on client side
    assert (
        "refresh_token" not in response.cookies
        or response.cookies.get("refresh_token") == ""
    )

    # Verify ALL active sessions for this user have been revoked
    db_session.expire_all()
    result = await db_session.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
        )
    )
    active_sessions = result.scalars().all()
    assert len(active_sessions) == 0


@pytest.mark.anyio
async def test_logout(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test logout revokes the current session and clears the cookie."""
    user = User(
        username="logoutuser",
        email="logout@example.com",
        hashed_password=hash_password("password"),
    )
    db_session.add(user)
    await db_session.commit()
    user_id = user.id

    login_res = await client.post(
        "/auth/login",
        data={"username": "logoutuser", "password": "password"},
    )
    refresh_token = login_res.cookies["refresh_token"]

    client.cookies.set("refresh_token", refresh_token)
    logout_res = await client.post("/auth/logout")
    assert logout_res.status_code == 204
    assert (
        "refresh_token" not in logout_res.cookies
        or logout_res.cookies.get("refresh_token") == ""
    )

    # Verify session is revoked in DB
    result = await db_session.execute(
        select(RefreshToken).where(RefreshToken.user_id == user_id)
    )
    session = result.scalar_one()
    assert session.revoked_at is not None


@pytest.mark.anyio
async def test_logout_all(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test logout-all revokes all sessions belonging to the user and clears cookie."""
    user = User(
        username="logoutalluser",
        email="logoutall@example.com",
        hashed_password=hash_password("password"),
    )
    db_session.add(user)
    await db_session.commit()
    user_id = user.id

    # Establish multiple sessions
    for _ in range(3):
        await client.post(
            "/auth/login",
            data={"username": "logoutalluser", "password": "password"},
        )

    # Verify 3 active sessions exist
    result = await db_session.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
        )
    )
    assert len(result.scalars().all()) == 3

    # Authenticate via access token header for logout-all
    login_res = await client.post(
        "/auth/login",
        data={"username": "logoutalluser", "password": "password"},
    )
    access_token = login_res.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {access_token}"

    logout_all_res = await client.post("/auth/logout-all")
    assert logout_all_res.status_code == 204

    # Verify cookie deleted
    assert (
        "refresh_token" not in logout_all_res.cookies
        or logout_all_res.cookies.get("refresh_token") == ""
    )

    # Verify all sessions are revoked
    db_session.expire_all()
    result = await db_session.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
        )
    )
    assert len(result.scalars().all()) == 0


@pytest.mark.anyio
async def test_get_sessions(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test listing sessions shows all active sessions with correct is_current flag."""
    user = User(
        username="sessionuser",
        email="sessions@example.com",
        hashed_password=hash_password("password"),
    )
    db_session.add(user)
    await db_session.commit()
    user_id = user.id

    # Create session 1
    login_res1 = await client.post(
        "/auth/login",
        data={"username": "sessionuser", "password": "password"},
    )
    token_1 = login_res1.cookies["refresh_token"]

    # Create session 2
    login_res2 = await client.post(
        "/auth/login",
        data={"username": "sessionuser", "password": "password"},
    )
    access_token = login_res2.json()["access_token"]

    # Use session 1 cookie, but authenticate request via session 2 access token
    client.cookies.set("refresh_token", token_1)
    client.headers["Authorization"] = f"Bearer {access_token}"

    response = await client.get("/auth/sessions")
    assert response.status_code == 200
    sessions = response.json()
    assert len(sessions) == 2

    # Check that session 1 is marked as current (because its cookie was sent), session 2 is not
    current_count = sum(1 for s in sessions if s["is_current"])
    assert current_count == 1


@pytest.mark.anyio
async def test_revoke_specific_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test revoking a specific session."""
    user = User(
        username="revokeuser",
        email="revoke_spec@example.com",
        hashed_password=hash_password("password"),
    )
    db_session.add(user)
    await db_session.commit()

    # Login to get access token
    login_res = await client.post(
        "/auth/login",
        data={"username": "revokeuser", "password": "password"},
    )
    access_token = login_res.json()["access_token"]
    refresh_token = login_res.cookies["refresh_token"]

    client.headers["Authorization"] = f"Bearer {access_token}"
    client.cookies.set("refresh_token", refresh_token)

    # Get active session ID
    sess_res = await client.get("/auth/sessions")
    session_id = sess_res.json()[0]["id"]

    # Revoke that specific session
    revoke_res = await client.delete(f"/auth/sessions/{session_id}")
    assert revoke_res.status_code == 204

    # Verify session is revoked
    db_session.expire_all()
    result = await db_session.execute(
        select(RefreshToken).where(RefreshToken.id == uuid.UUID(session_id))
    )
    session = result.scalar_one()
    assert session.revoked_at is not None

    # Verify cookie was cleared (since we revoked our current session)
    assert (
        "refresh_token" not in revoke_res.cookies
        or revoke_res.cookies.get("refresh_token") == ""
    )


@pytest.mark.anyio
async def test_revoke_session_not_owned(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test that users cannot revoke other users' sessions."""
    user1 = User(
        username="user1",
        email="user1@example.com",
        hashed_password=hash_password("password"),
    )
    user2 = User(
        username="user2",
        email="user2@example.com",
        hashed_password=hash_password("password"),
    )
    db_session.add_all([user1, user2])
    await db_session.commit()
    user2_id = user2.id

    # Establish session for user 2
    session_user2 = RefreshToken(
        user_id=user2_id,
        token_hash="hash",
        jti="user2-jti",
    )
    db_session.add(session_user2)
    await db_session.commit()
    session_user2_id = session_user2.id

    # Log in user 1
    login_res = await client.post(
        "/auth/login",
        data={"username": "user1", "password": "password"},
    )
    access_token = login_res.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {access_token}"

    # Try to revoke user 2's session
    response = await client.delete(f"/auth/sessions/{session_user2_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"


@pytest.mark.anyio
async def test_cleanup_endpoint(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test cleaning up expired sessions."""
    admin_user = User(
        username="adminuser",
        email="admin@example.com",
        hashed_password=hash_password("password"),
        role=UserRole.ADMIN,
    )
    regular_user = User(
        username="reguser",
        email="reg@example.com",
        hashed_password=hash_password("password"),
        role=UserRole.USER,
    )
    db_session.add_all([admin_user, regular_user])
    await db_session.commit()
    regular_user_id = regular_user.id

    # 1. Log in both users first to get their access tokens (runs any login-time cleanup)
    login_res_admin = await client.post(
        "/auth/login",
        data={"username": "adminuser", "password": "password"},
    )
    admin_token = login_res_admin.json()["access_token"]

    login_res_reg = await client.post(
        "/auth/login",
        data={"username": "reguser", "password": "password"},
    )
    reg_token = login_res_reg.json()["access_token"]

    # 2. Add an expired session AFTER both logins have completed
    expired_session = RefreshToken(
        user_id=regular_user_id,
        token_hash="expired-hash",
        jti="expired-jti",
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    db_session.add(expired_session)
    await db_session.commit()

    # 3. Try to clean up as regular user (should fail with 403, no background task run)
    client.headers["Authorization"] = f"Bearer {reg_token}"
    res = await client.post("/auth/cleanup")
    assert res.status_code == 403
    assert "Only admins" in res.json()["detail"]

    # 4. Clean up as admin (should succeed)
    client.headers["Authorization"] = f"Bearer {admin_token}"
    res2 = await client.post("/auth/cleanup")
    assert res2.status_code == 200
    assert res2.json()["deleted_sessions"] >= 1


@pytest.mark.anyio
async def test_get_me_unauthorized(client: AsyncClient) -> None:
    """Test getting profile without valid token."""
    client.headers["Authorization"] = "Bearer invalid-token"
    res = await client.get("/auth/me")
    assert res.status_code == 401
    assert "could not validate credentials" in res.json()["detail"].lower()


@pytest.mark.anyio
async def test_get_me_inactive(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test getting profile fails for inactive user."""
    user = User(
        username="inactiveme",
        email="inactiveme@example.com",
        hashed_password=hash_password("password"),
        is_active=False,
    )
    db_session.add(user)
    await db_session.commit()
    user_id = user.id

    from ai_trading_discipline_copilot.core.security import create_access_token

    token, _ = create_access_token(str(user_id))
    client.headers["Authorization"] = f"Bearer {token}"
    res = await client.get("/auth/me")
    assert res.status_code == 401


@pytest.mark.anyio
async def test_get_me_invalid_uuid(client: AsyncClient) -> None:
    """Test getting profile fails with invalid sub UUID payload."""
    from datetime import timedelta
    from ai_trading_discipline_copilot.core.security import _create_token

    token, _ = _create_token("invalid-uuid", timedelta(minutes=10), "access")
    client.headers["Authorization"] = f"Bearer {token}"
    res = await client.get("/auth/me")
    assert res.status_code == 401


@pytest.mark.anyio
async def test_get_me_user_not_found(client: AsyncClient) -> None:
    """Test getting profile fails if user no longer exists."""
    from ai_trading_discipline_copilot.core.security import create_access_token

    token, _ = create_access_token(str(uuid.uuid4()))
    client.headers["Authorization"] = f"Bearer {token}"
    res = await client.get("/auth/me")
    assert res.status_code == 401


@pytest.mark.anyio
async def test_logout_missing_token(client: AsyncClient) -> None:
    """Test logout fails if cookie is missing."""
    client.cookies.clear()
    res = await client.post("/auth/logout")
    assert res.status_code == 401


@pytest.mark.anyio
async def test_logout_invalid_token(client: AsyncClient) -> None:
    """Test logout fails if cookie is invalid."""
    client.cookies.set("refresh_token", "invalid-refresh-token")
    res = await client.post("/auth/logout")
    assert res.status_code == 401


@pytest.mark.anyio
async def test_refresh_token_invalid_format(client: AsyncClient) -> None:
    """Test token rotation fails with malformed cookie format."""
    client.cookies.set("refresh_token", "invalid-token-format")
    res = await client.post("/auth/refresh")
    assert res.status_code == 401


@pytest.mark.anyio
async def test_refresh_token_expired(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test token rotation fails if token is expired."""
    user = User(
        username="expiredrefresh",
        email="expiredref@example.com",
        hashed_password=hash_password("password"),
    )
    db_session.add(user)
    await db_session.commit()
    user_id = user.id

    from datetime import timedelta
    from ai_trading_discipline_copilot.core.security import _create_token

    token, jti = _create_token(str(user_id), timedelta(seconds=-10), "refresh")

    session = RefreshToken(
        user_id=user_id,
        token_hash="hash",
        jti=jti,
        expires_at=datetime.now(UTC) - timedelta(seconds=10),
    )
    db_session.add(session)
    await db_session.commit()

    client.cookies.set("refresh_token", token)
    res = await client.post("/auth/refresh")
    assert res.status_code == 401


@pytest.mark.anyio
async def test_refresh_token_inactive_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test token rotation fails if user is inactive."""
    user = User(
        username="inactiveupdater",
        email="inactiveup@example.com",
        hashed_password=hash_password("password"),
        is_active=False,
    )
    db_session.add(user)
    await db_session.commit()
    user_id = user.id

    from ai_trading_discipline_copilot.core.security import (
        create_refresh_token,
        hash_refresh_token,
    )

    token, jti = create_refresh_token(str(user_id))

    session = RefreshToken(
        user_id=user_id,
        token_hash=hash_refresh_token(token),
        jti=jti,
    )
    db_session.add(session)
    await db_session.commit()

    client.cookies.set("refresh_token", token)
    res = await client.post("/auth/refresh")
    assert res.status_code == 401
    assert "disabled" in res.json()["detail"].lower()


@pytest.mark.anyio
async def test_refresh_token_user_not_found(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test token rotation fails if user is not found in database."""
    user = User(
        username="deleteduser",
        email="deleted@example.com",
        hashed_password=hash_password("password"),
    )
    db_session.add(user)
    await db_session.commit()
    user_id = user.id

    from ai_trading_discipline_copilot.core.security import (
        create_refresh_token,
        hash_refresh_token,
    )

    token, jti = create_refresh_token(str(user_id))

    session = RefreshToken(
        user_id=user_id,
        token_hash=hash_refresh_token(token),
        jti=jti,
    )
    db_session.add(session)
    await db_session.commit()

    # Mock db.execute to return None when searching for User
    original_execute = AsyncSession.execute

    async def mock_execute(self, stmt, *args, **kwargs):
        if "FROM users" in str(stmt) or "users.id" in str(stmt):

            class MockResult:

                def scalar_one_or_none(self):
                    return None

            return MockResult()
        return await original_execute(self, stmt, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", mock_execute)

    client.cookies.set("refresh_token", token)
    res = await client.post("/auth/refresh")
    assert res.status_code == 401
    assert "user not found" in res.json()["detail"].lower()


# ── Direct Service-Level Tests for Coverage ──────────────────────────


@pytest.mark.anyio
async def test_direct_register_duplicate(db_session: AsyncSession) -> None:
    """Directly test UserService.register_user duplication exceptions."""
    from ai_trading_discipline_copilot.core.exceptions import ConflictException
    from ai_trading_discipline_copilot.schemas.user import UserCreate
    from ai_trading_discipline_copilot.services.user_service import UserService

    user = User(
        username="directdup",
        email="direct@example.com",
        hashed_password=hash_password("password"),
    )
    db_session.add(user)
    await db_session.commit()

    # Duplicate username
    with pytest.raises(ConflictException) as exc:
        await UserService.register_user(
            db_session,
            UserCreate(
                username="directdup",
                email="other@example.com",
                password="password",
            ),
        )
    assert "Username already exists" in str(exc.value.detail)

    # Duplicate email
    with pytest.raises(ConflictException) as exc:
        await UserService.register_user(
            db_session,
            UserCreate(
                username="other",
                email="direct@example.com",
                password="password",
            ),
        )
    assert "Email already exists" in str(exc.value.detail)


@pytest.mark.anyio
async def test_direct_auth_service_methods(db_session: AsyncSession) -> None:
    """Directly test AuthService._authenticate_user exceptions."""
    from ai_trading_discipline_copilot.core.exceptions import UnauthorizedException
    from ai_trading_discipline_copilot.services.auth_service import AuthService

    user = User(
        username="directauth",
        email="directauth@example.com",
        hashed_password=hash_password("password"),
        is_active=False,
    )
    db_session.add(user)
    await db_session.commit()

    # Inactive user
    with pytest.raises(UnauthorizedException) as exc:
        await AuthService._authenticate_user(db_session, "directauth", "password")
    assert "disabled" in str(exc.value.detail).lower()

    # Wrong password
    with pytest.raises(UnauthorizedException) as exc:
        await AuthService._authenticate_user(db_session, "directauth", "wrong")
    assert "invalid username" in str(exc.value.detail).lower()

    # Non-existent user
    with pytest.raises(UnauthorizedException) as exc:
        await AuthService._authenticate_user(db_session, "nonexistent", "password")
    assert "invalid username" in str(exc.value.detail).lower()


@pytest.mark.anyio
async def test_direct_logout_failures(db_session: AsyncSession) -> None:
    """Directly test AuthService.logout exceptions."""
    from fastapi import Response

    from ai_trading_discipline_copilot.core.exceptions import UnauthorizedException
    from ai_trading_discipline_copilot.services.auth_service import AuthService

    res = Response()
    # Missing token
    with pytest.raises(UnauthorizedException):
        await AuthService.logout(res, db_session, None)

    # Invalid token format
    with pytest.raises(UnauthorizedException):
        await AuthService.logout(res, db_session, "invalid-format")


@pytest.mark.anyio
async def test_direct_refresh_token_service_rotation_failures(
    db_session: AsyncSession,
) -> None:
    """Directly test RefreshTokenService exceptions."""
    from ai_trading_discipline_copilot.core.exceptions import UnauthorizedException
    from ai_trading_discipline_copilot.core.security import create_refresh_token
    from ai_trading_discipline_copilot.services.refresh_token_service import (
        RefreshTokenService,
    )

    # Invalid format
    with pytest.raises(UnauthorizedException):
        await RefreshTokenService.rotate(db_session, "invalid-format")

    # Session not found
    token, jti = create_refresh_token(str(uuid.uuid4()))
    with pytest.raises(UnauthorizedException) as exc:
        await RefreshTokenService.rotate(db_session, token)
    assert "not found" in str(exc.value.detail).lower()


@pytest.mark.anyio
async def test_direct_refresh_token_expired(db_session: AsyncSession) -> None:
    """Directly test rotating expired token session."""
    from ai_trading_discipline_copilot.core.exceptions import UnauthorizedException
    from ai_trading_discipline_copilot.core.security import _create_token
    from ai_trading_discipline_copilot.services.refresh_token_service import (
        RefreshTokenService,
    )

    user = User(
        username="expireduser",
        email="exp@example.com",
        hashed_password="pw",
    )
    db_session.add(user)
    await db_session.commit()

    from ai_trading_discipline_copilot.core.security import hash_refresh_token

    # Use 10 minutes delta so the JWT is valid and doesn't fail decoding
    token, jti = _create_token(str(user.id), timedelta(minutes=10), "refresh")
    session = RefreshToken(
        user_id=user.id,
        token_hash=hash_refresh_token(token),
        jti=jti,
        expires_at=datetime.now(UTC) - timedelta(seconds=10),
    )
    db_session.add(session)
    await db_session.commit()

    with pytest.raises(UnauthorizedException) as exc:
        await RefreshTokenService.rotate(db_session, token)
    assert "expired" in str(exc.value.detail).lower()


@pytest.mark.anyio
async def test_direct_refresh_token_mismatched_hash(db_session: AsyncSession) -> None:
    """Directly test rotating token session with mismatched token hash."""
    from ai_trading_discipline_copilot.core.exceptions import UnauthorizedException
    from ai_trading_discipline_copilot.core.security import create_refresh_token
    from ai_trading_discipline_copilot.services.refresh_token_service import (
        RefreshTokenService,
    )

    user = User(
        username="mismatchuser",
        email="mismatch@example.com",
        hashed_password="pw",
    )
    db_session.add(user)
    await db_session.commit()

    token, jti = create_refresh_token(str(user.id))
    session = RefreshToken(
        user_id=user.id,
        token_hash="wrong-hash-in-db",
        jti=jti,
    )
    db_session.add(session)
    await db_session.commit()

    with pytest.raises(UnauthorizedException) as exc:
        await RefreshTokenService.rotate(db_session, token)
    assert "invalid refresh token" in str(exc.value.detail).lower()


@pytest.mark.anyio
async def test_direct_refresh_token_inactive_user(db_session: AsyncSession) -> None:
    """Directly test rotating session with inactive user status."""
    from ai_trading_discipline_copilot.core.exceptions import UnauthorizedException
    from ai_trading_discipline_copilot.core.security import (
        create_refresh_token,
        hash_refresh_token,
    )
    from ai_trading_discipline_copilot.services.refresh_token_service import (
        RefreshTokenService,
    )

    user = User(
        username="inactiveupd",
        email="inactiveupd@example.com",
        hashed_password="pw",
        is_active=False,
    )
    db_session.add(user)
    await db_session.commit()

    token, jti = create_refresh_token(str(user.id))
    session = RefreshToken(
        user_id=user.id,
        token_hash=hash_refresh_token(token),
        jti=jti,
    )
    db_session.add(session)
    await db_session.commit()

    with pytest.raises(UnauthorizedException) as exc:
        await RefreshTokenService.rotate(db_session, token)
    assert "disabled" in str(exc.value.detail).lower()


@pytest.mark.anyio
async def test_direct_refresh_token_reuse(db_session: AsyncSession) -> None:
    """Directly test rotating session that was already revoked (Reuse Detection)."""
    from ai_trading_discipline_copilot.core.exceptions import UnauthorizedException
    from ai_trading_discipline_copilot.core.security import (
        create_refresh_token,
        hash_refresh_token,
    )
    from ai_trading_discipline_copilot.services.refresh_token_service import (
        RefreshTokenService,
    )

    user = User(
        username="reuseuser2",
        email="reuse2@example.com",
        hashed_password="pw",
    )
    db_session.add(user)
    await db_session.commit()

    token, jti = create_refresh_token(str(user.id))
    session = RefreshToken(
        user_id=user.id,
        token_hash=hash_refresh_token(token),
        jti=jti,
        revoked_at=datetime.now(UTC),
    )
    db_session.add(session)
    await db_session.commit()

    with pytest.raises(UnauthorizedException) as exc:
        await RefreshTokenService.rotate(db_session, token)
    assert "revoked due to reuse detection" in str(exc.value.detail).lower()
