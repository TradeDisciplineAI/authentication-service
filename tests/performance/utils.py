"""Utility and helper functions for Locust load testing."""

import logging
from typing import Any

from locust.clients import ResponseContextManager

logger = logging.getLogger(__name__)


def get_auth_headers(access_token: str | None = None) -> dict[str, str]:
    """Construct HTTP headers including Bearer authorization token if present.

    Args:
        access_token: Optional JWT access token.

    Returns:
        Header dictionary.
    """
    headers = {
        "Accept": "application/json",
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    return headers


def parse_json_response(response: ResponseContextManager) -> dict[str, Any] | None:
    """Safely extract JSON body from a Locust response context.

    Args:
        response: Locust response object.

    Returns:
        Parsed JSON dictionary or None if decoding fails.
    """
    try:
        return response.json()  # type: ignore[no-any-return]
    except Exception as exc:
        logger.warning("Failed to parse JSON response from %s: %s", response.url, exc)
        return None
