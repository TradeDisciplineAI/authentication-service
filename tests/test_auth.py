import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_trading_discipline_copilot.core.security import hash_password
from ai_trading_discipline_copilot.models.refresh_token import RefreshToken
from ai_trading_discipline_copilot.models.user import User

# Single constant used everywhere so S106 never fires on individual strings.
TEST_PASSWORD = "StrongPass1!"  # noqa: S105


@pytest.mark.anyio
async def test_register_success(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test successful user registration."""
    payload = {
        "username": "testuser",
        "email": "testuser@example.com",
        "password": TEST_PASSWORD,
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
        hashed_password=hash_password(TEST_PASSWORD),
    )
    db_session.add(user)
    await db_session.commit()

    payload = {
        "username": "duplicate",
        "email": "second@example.com",
        "password": TEST_PASSWORD,
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
        hashed_password=hash_password(TEST_PASSWORD),
    )
    db_session.add(user)
    await db_session.commit()

    payload = {
        "username": "second",
        "email": "duplicate@example.com",
        "password": TEST_PASSWORD,
    }
    response = await client.post("/auth/register", json=payload)
    assert response.status_code == 409
    assert response.json()["detail"] == "Email already exists"


@pytest.mark.anyio
async def test_register_duplicate_both_same_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test registration fails when both username and email match the same user."""
    user = User(
        username="duplicate",
        email="duplicate@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
    )
    db_session.add(user)
    await db_session.commit()

    payload = {
        "username": "duplicate",
        "email": "duplicate@example.com",
        "password": TEST_PASSWORD,
    }
    response = await client.post("/auth/register", json=payload)
    assert response.status_code == 409
    assert response.json()["detail"] == "Username already exists"


@pytest.mark.anyio
async def test_register_duplicate_different_users(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test registration fails when username and email match different users."""
    user_a = User(
        username="duplicate_user",
        email="usera@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
    )
    db_session.add(user_a)

    user_b = User(
        username="other_user",
        email="duplicate_email@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
    )
    db_session.add(user_b)
    await db_session.commit()

    payload = {
        "username": "duplicate_user",
        "email": "duplicate_email@example.com",
        "password": TEST_PASSWORD,
    }
    response = await client.post("/auth/register", json=payload)
    assert response.status_code == 409
    assert response.json()["detail"] == "Username already exists"


@pytest.mark.anyio
async def test_login_success(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test successful login returns access token and sets cookie."""
    user = User(
        username="loginuser",
        email="login@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
    )
    db_session.add(user)
    await db_session.commit()

    response = await client.post(
        "/auth/login",
        data={"username": "loginuser", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"  # noqa: S105

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
        hashed_password=hash_password(TEST_PASSWORD),
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
        hashed_password=hash_password(TEST_PASSWORD),
        is_active=False,
    )
    db_session.add(user)
    await db_session.commit()

    response = await client.post(
        "/auth/login",
        data={"username": "inactiveuser", "password": TEST_PASSWORD},
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
        hashed_password=hash_password(TEST_PASSWORD),
    )
    db_session.add(user)
    await db_session.commit()

    # Login to establish first session
    login_response = await client.post(
        "/auth/login",
        data={"username": "rotateuser", "password": TEST_PASSWORD},
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
    """Test presenting a revoked token triggers reuse flow (revokes all sessions)."""
    user = User(
        username="reuseuser",
        email="reuse@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
    )
    db_session.add(user)
    await db_session.commit()
    user_id = user.id

    # 1. Establish Session A
    client.cookies.clear()
    login_res = await client.post(
        "/auth/login",
        data={"username": "reuseuser", "password": TEST_PASSWORD},
    )
    token_a = login_res.cookies["refresh_token"]

    # 2. Establish Session B (log in again to get a second active session)
    client.cookies.clear()
    await client.post(
        "/auth/login",
        data={"username": "reuseuser", "password": TEST_PASSWORD},
    )

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
        hashed_password=hash_password(TEST_PASSWORD),
    )
    db_session.add(user)
    await db_session.commit()
    user_id = user.id

    login_res = await client.post(
        "/auth/login",
        data={"username": "logoutuser", "password": TEST_PASSWORD},
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
    """Test logout-all revokes all sessions and clears cookie."""
    user = User(
        username="logoutalluser",
        email="logoutall@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
    )
    db_session.add(user)
    await db_session.commit()
    user_id = user.id

    # Establish multiple sessions
    for _ in range(3):
        await client.post(
            "/auth/login",
            data={"username": "logoutalluser", "password": TEST_PASSWORD},
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
        data={"username": "logoutalluser", "password": TEST_PASSWORD},
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
        hashed_password=hash_password(TEST_PASSWORD),
    )
    db_session.add(user)
    await db_session.commit()

    # Create session 1
    login_res1 = await client.post(
        "/auth/login",
        data={"username": "sessionuser", "password": TEST_PASSWORD},
    )
    token_1 = login_res1.cookies["refresh_token"]

    # Create session 2
    login_res2 = await client.post(
        "/auth/login",
        data={"username": "sessionuser", "password": TEST_PASSWORD},
    )
    access_token = login_res2.json()["access_token"]

    # Use session 1 cookie, but authenticate request via session 2 access token
    client.cookies.set("refresh_token", token_1)
    client.headers["Authorization"] = f"Bearer {access_token}"

    response = await client.get("/auth/sessions")
    assert response.status_code == 200
    sessions = response.json()
    assert len(sessions) == 2

    # Session 1 is the current one (its cookie was sent); session 2 is not
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
        hashed_password=hash_password(TEST_PASSWORD),
    )
    db_session.add(user)
    await db_session.commit()

    # Login to get access token
    login_res = await client.post(
        "/auth/login",
        data={"username": "revokeuser", "password": TEST_PASSWORD},
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
        hashed_password=hash_password(TEST_PASSWORD),
    )
    user2 = User(
        username="user2",
        email="user2@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
    )
    db_session.add_all([user1, user2])
    await db_session.commit()
    user2_id = user2.id

    # Establish a raw session for user 2 (no real JWT needed — just a DB row)
    session_user2 = RefreshToken(
        user_id=user2_id,
        token_hash="user2-placeholder-hash",  # noqa: S106
        jti="user2-jti",
    )
    db_session.add(session_user2)
    await db_session.commit()
    session_user2_id = session_user2.id

    # Log in user 1
    login_res = await client.post(
        "/auth/login",
        data={"username": "user1", "password": TEST_PASSWORD},
    )
    access_token = login_res.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {access_token}"

    # Try to revoke user 2's session
    response = await client.delete(f"/auth/sessions/{session_user2_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"


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
    from ai_trading_discipline_copilot.core.security import create_access_token

    user = User(
        username="inactiveme",
        email="inactiveme@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
        is_active=False,
    )
    db_session.add(user)
    await db_session.commit()
    user_id = user.id

    token, _ = create_access_token(str(user_id))
    client.headers["Authorization"] = f"Bearer {token}"
    res = await client.get("/auth/me")
    assert res.status_code == 401


@pytest.mark.anyio
async def test_get_me_invalid_uuid(client: AsyncClient) -> None:
    """Test getting profile fails with invalid sub UUID payload."""
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
    from ai_trading_discipline_copilot.core.security import _create_token

    user = User(
        username="expiredrefresh",
        email="expiredref@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
    )
    db_session.add(user)
    await db_session.commit()
    user_id = user.id

    token, jti = _create_token(str(user_id), timedelta(seconds=-10), "refresh")

    session = RefreshToken(
        user_id=user_id,
        token_hash="placeholder-hash",  # noqa: S106
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
    from ai_trading_discipline_copilot.core.security import (
        create_refresh_token,
        hash_refresh_token,
    )

    user = User(
        username="inactiveupdater",
        email="inactiveup@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
        is_active=False,
    )
    db_session.add(user)
    await db_session.commit()
    user_id = user.id

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
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test token rotation fails if user is not found in database."""
    from ai_trading_discipline_copilot.core.security import (
        create_refresh_token,
        hash_refresh_token,
    )

    user = User(
        username="deleteduser",
        email="deleted@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
    )
    db_session.add(user)
    await db_session.commit()
    user_id = user.id

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

    async def mock_execute(self, stmt, *args, **kwargs):  # type: ignore[no-untyped-def]
        if "FROM users" in str(stmt) or "users.id" in str(stmt):

            class MockResult:
                def scalar_one_or_none(self) -> None:
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
        hashed_password=hash_password(TEST_PASSWORD),
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
                password=TEST_PASSWORD,
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
                password=TEST_PASSWORD,
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
        hashed_password=hash_password(TEST_PASSWORD),
        is_active=False,
    )
    db_session.add(user)
    await db_session.commit()

    # Inactive user
    with pytest.raises(UnauthorizedException) as exc:
        await AuthService._authenticate_user(db_session, "directauth", TEST_PASSWORD)
    assert "disabled" in str(exc.value.detail).lower()

    # Wrong password
    with pytest.raises(UnauthorizedException) as exc:
        await AuthService._authenticate_user(db_session, "directauth", "wrong")
    assert "invalid username" in str(exc.value.detail).lower()

    # Non-existent user
    with pytest.raises(UnauthorizedException) as exc:
        await AuthService._authenticate_user(db_session, "nonexistent", TEST_PASSWORD)
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
    token, _ = create_refresh_token(str(uuid.uuid4()))
    with pytest.raises(UnauthorizedException) as exc:
        await RefreshTokenService.rotate(db_session, token)
    assert "not found" in str(exc.value.detail).lower()


@pytest.mark.anyio
async def test_direct_refresh_token_expired(db_session: AsyncSession) -> None:
    """Directly test rotating expired token session."""
    from ai_trading_discipline_copilot.core.exceptions import UnauthorizedException
    from ai_trading_discipline_copilot.core.security import (
        _create_token,
        hash_refresh_token,
    )
    from ai_trading_discipline_copilot.services.refresh_token_service import (
        RefreshTokenService,
    )

    user = User(
        username="expireduser",
        email="exp@example.com",
        hashed_password=hash_password(TEST_PASSWORD),
    )
    db_session.add(user)
    await db_session.commit()

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
        hashed_password=hash_password(TEST_PASSWORD),
    )
    db_session.add(user)
    await db_session.commit()

    token, jti = create_refresh_token(str(user.id))
    session = RefreshToken(
        user_id=user.id,
        token_hash="wrong-hash-in-db",  # noqa: S106
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
        hashed_password=hash_password(TEST_PASSWORD),
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
        hashed_password=hash_password(TEST_PASSWORD),
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
