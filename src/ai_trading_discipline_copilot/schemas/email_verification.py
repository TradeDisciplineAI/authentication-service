"""Schemas for email verification."""

from pydantic import BaseModel, EmailStr


class VerifyEmailRequest(BaseModel):
    """Request to verify email."""

    token: str


class VerifyEmailResponse(BaseModel):
    """Response for email verification."""

    message: str


class ResendVerificationRequest(BaseModel):
    """Request to resend verification email."""

    email: EmailStr


class ResendVerificationResponse(BaseModel):
    """Response for resending verification email."""

    message: str
