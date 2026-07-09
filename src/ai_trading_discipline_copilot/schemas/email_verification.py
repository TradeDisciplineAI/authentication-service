"""Schemas for email verification."""

from pydantic import BaseModel, EmailStr


class VerifyEmailRequest(BaseModel):
    """Request to verify email."""

    token: str


class VerifyEmailResponse(BaseModel):
    """Response for email verification."""

    message: str
    access_token: str | None = None
    token_type: str | None = None


class ResendVerificationRequest(BaseModel):
    """Request to resend verification email."""

    username_or_email: str


class ResendVerificationResponse(BaseModel):
    """Response for resending verification email."""

    message: str
