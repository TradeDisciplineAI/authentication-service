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

    @staticmethod
    async def send_verification_email(
        *,
        to: str,
        verification_url: str,
    ) -> None:
        """Send email verification link using Resend."""
        import html
        from datetime import UTC, datetime

        escaped_app_name = html.escape(settings.app_name)
        escaped_verification_url = html.escape(verification_url)
        current_year = datetime.now(UTC).year

        html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Verify your email</title>
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
      <p>Thank you for registering.</p>
      <p>Please click the button below to verify your email:</p>
      <div class="button-container">
        <a href="{escaped_verification_url}"
           class="button"
           target="_blank">Verify Email</a>
      </div>
      <p>This verification link is only valid for <strong>24 hours</strong>.</p>
      <p>If you did not request this, you can safely ignore this email.</p>
      <p class="url-text">
        If you're having trouble clicking the button, copy and paste the URL below:<br>
        <a href="{escaped_verification_url}">{escaped_verification_url}</a>
      </p>
    </div>
    <div class="footer">
      &copy; {current_year} {escaped_app_name}. All rights reserved.
    </div>
  </div>
</body>
</html>"""

        await EmailService.send_email(
            to=to,
            subject="Verify your email",
            html=html_content,
        )
