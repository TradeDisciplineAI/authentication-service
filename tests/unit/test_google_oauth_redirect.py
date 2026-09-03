from unittest.mock import MagicMock

from ai_trading_discipline_copilot.core.config import get_settings
from ai_trading_discipline_copilot.routers.auth import _get_google_redirect_uri


def test_google_redirect_uri_with_public_api_url():
    settings = get_settings()
    original_public_api = settings.public_api_url
    try:
        settings.public_api_url = "https://tradingcopilot.duckdns.org"
        mock_request = MagicMock()
        mock_request.url_for.return_value.path = "/auth/oauth2/google/callback"

        redirect_uri = _get_google_redirect_uri(mock_request)
        assert (
            redirect_uri
            == "https://tradingcopilot.duckdns.org/auth/oauth2/google/callback"
        )
    finally:
        settings.public_api_url = original_public_api


def test_google_redirect_uri_local_fallback():
    settings = get_settings()
    original_public_api = settings.public_api_url
    try:
        settings.public_api_url = None
        mock_request = MagicMock()
        mock_request.url_for.return_value = (
            "http://localhost:8000/auth/oauth2/google/callback"
        )

        redirect_uri = _get_google_redirect_uri(mock_request)
        assert redirect_uri == "http://localhost:8000/auth/oauth2/google/callback"
    finally:
        settings.public_api_url = original_public_api
