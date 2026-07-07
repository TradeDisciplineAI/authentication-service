"""Schemas for password reset."""

from pydantic import BaseModel, EmailStr, Field


class ForgotPasswordRequest(BaseModel):
    """Request to initiate password reset."""

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Request to reset password."""

    token: str = Field(min_length=32)
    new_password: str = Field(min_length=8, max_length=72)


class ForgotPasswordResponse(BaseModel):
    """Response to forgot password request."""

    message: str


class ResetPasswordResponse(BaseModel):
    """Response to reset password execution."""

    message: str

