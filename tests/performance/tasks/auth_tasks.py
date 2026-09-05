"""Authentication task definitions for Locust load tests.

Provides reusable auth operations: login, token refresh, profile fetch, and logout.
"""

import logging

from locust.clients import HttpSession

from tests.performance.config import config
from tests.performance.utils import get_auth_headers, parse_json_response

logger = logging.getLogger(__name__)


def login_user(client: HttpSession, username: str, password: str) -> str | None:
    """Authenticate virtual user once using OAuth2 form data.

    Args:
        client: Locust HTTP session client.
        username: Account username/email.
        password: Account password.

    Returns:
        Access token string if login succeeded, otherwise None.
    """
    payload = {
        "username": username,
        "password": password,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    with client.post(
        "/auth/login",
        data=payload,
        headers=headers,
        catch_response=True,
        name="/auth/login",
    ) as response:
        if response.status_code == 200:
            data = parse_json_response(response)
            if data and "access_token" in data:
                response.success()

                # Ensure refresh_token cookie is stored on client session
                cookie_name = config.COOKIE_NAME
                if cookie_name in response.cookies:
                    cookie_val = response.cookies[cookie_name]
                    client.cookies.set(cookie_name, cookie_val, path=config.COOKIE_PATH)

                return str(data["access_token"])
            response.failure("Login response missing access_token")
        elif response.status_code == 429:
            response.failure("Login rate limited (HTTP 429 Too Many Requests)")
        else:
            response.failure(f"Login failed with status code {response.status_code}")
    return None


def refresh_token(client: HttpSession) -> str | None:
    """Rotate refresh token and issue a new access token.

    Args:
        client: Locust HTTP session client (preserves refresh_token cookie).

    Returns:
        New access token string if successful, otherwise None.
    """
    cookie_name = config.COOKIE_NAME

    # Check if client has the refresh cookie before making request
    has_cookie = any(cookie.name == cookie_name for cookie in client.cookies)
    if not has_cookie:
        logger.debug("Skipping /auth/refresh because no refresh cookie is present")
        return None

    with client.post(
        "/auth/refresh",
        catch_response=True,
        name="/auth/refresh",
    ) as response:
        if response.status_code == 200:
            data = parse_json_response(response)
            if data and "access_token" in data:
                response.success()

                # Preserve rotated cookie if present
                if cookie_name in response.cookies:
                    cookie_val = response.cookies[cookie_name]
                    client.cookies.set(cookie_name, cookie_val, path=config.COOKIE_PATH)

                return str(data["access_token"])
            response.failure("Refresh response missing access_token")
        else:
            response.failure(
                f"Token refresh failed with status code {response.status_code}"
            )
    return None


def get_user_profile(client: HttpSession, access_token: str | None) -> bool:
    """Fetch authenticated user profile (`/auth/me`).

    Args:
        client: Locust HTTP session client.
        access_token: Current JWT access token.

    Returns:
        True if request succeeded, False otherwise.
    """
    if not access_token:
        return False

    headers = get_auth_headers(access_token)
    with client.get(
        "/auth/me",
        headers=headers,
        catch_response=True,
        name="/auth/me",
    ) as response:
        if response.status_code == 200:
            response.success()
            return True
        response.failure(f"Get profile failed with status code {response.status_code}")
    return False


def logout_user(client: HttpSession) -> bool:
    """Log out current virtual user session (`/auth/logout`).

    Args:
        client: Locust HTTP session client.

    Returns:
        True if logout succeeded, False otherwise.
    """
    cookie_name = config.COOKIE_NAME
    has_cookie = any(cookie.name == cookie_name for cookie in client.cookies)
    if not has_cookie:
        return False

    with client.post(
        "/auth/logout",
        catch_response=True,
        name="/auth/logout",
    ) as response:
        if response.status_code in (200, 204):
            response.success()
            return True
        response.failure(f"Logout failed with status code {response.status_code}")
    return False
