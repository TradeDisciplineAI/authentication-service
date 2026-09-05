from collections.abc import Generator

import pytest


@pytest.fixture(autouse=True)
def mock_resend_emails() -> Generator[None]:
    """Globally mock resend email calls during tests to prevent API key errors."""
    from unittest.mock import patch

    with (
        patch("resend.Emails.send") as _mock_send,
        patch("resend.Emails.send_async") as _mock_send_async,
    ):
        yield


@pytest.fixture(autouse=True)
def disable_limiter() -> Generator[None]:
    """Globally disable the slowapi rate limiter for functional tests."""
    from ai_trading_discipline_copilot.core.limiter import limiter

    limiter.enabled = False
    yield
    limiter.enabled = True
