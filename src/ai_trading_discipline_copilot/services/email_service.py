"""Email service powered by Resend."""

from __future__ import annotations

import resend

from ai_trading_discipline_copilot.core.config import get_settings

settings = get_settings()

resend.api_key = settings.resend_api_key.get_secret_value()


class EmailService:
    """Business logic for sending emails."""

    @staticmethod
    async def send_email(
        *,
        to: str,
        subject: str,
        html: str,
    ) -> None:
        """Send an email using Resend."""

        resend.Emails.send(
            {
                "from": settings.email_from,
                "to": to,
                "subject": subject,
                "html": html,
            }
        )
