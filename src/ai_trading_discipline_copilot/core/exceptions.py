"""Custom HTTP exception classes for the application."""

from fastapi import HTTPException


class AppException(HTTPException):
    """Base class for all application HTTP exceptions."""

    def __init__(self, detail: str, status_code: int) -> None:
        super().__init__(status_code=status_code, detail=detail)


class BadRequestException(AppException):
    """400 — Invalid input or malformed request."""

    def __init__(self, detail: str = "Bad request") -> None:
        super().__init__(detail=detail, status_code=400)


class UnauthorizedException(AppException):
    """401 — Missing, invalid, or expired authentication token."""

    def __init__(self, detail: str = "Not authenticated") -> None:
        super().__init__(detail=detail, status_code=401)


class ForbiddenException(AppException):
    """403 — Authenticated but not authorized to access this resource."""

    def __init__(self, detail: str = "Access forbidden") -> None:
        super().__init__(detail=detail, status_code=403)


class NotFoundException(AppException):
    """404 — Requested resource does not exist."""

    def __init__(self, detail: str = "Resource not found") -> None:
        super().__init__(detail=detail, status_code=404)


class ConflictException(AppException):
    """409 — Request conflicts with current state (e.g. duplicate email)."""

    def __init__(self, detail: str = "Resource already exists") -> None:
        super().__init__(detail=detail, status_code=409)


class UnprocessableEntityException(AppException):
    """422 — Semantically invalid request (supplements Pydantic validation)."""

    def __init__(self, detail: str = "Unprocessable entity") -> None:
        super().__init__(detail=detail, status_code=422)


class InternalServerException(AppException):
    """500 — Unexpected server-side failure."""

    def __init__(self, detail: str = "Internal server error") -> None:
        super().__init__(detail=detail, status_code=500)
