"""Application/domain error taxonomy.

These are framework-independent errors. The API layer converts them into HTTP
responses (see `app.shared.exceptions.status_for`), so the domain never needs
to import FastAPI or raise `HTTPException`.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any


class AppError(Exception):
    """Base class for all handled application/domain errors."""

    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR
    default_message: str = "Internal error."

    def __init__(self, message: str | None = None, *, detail: Any | None = None) -> None:
        super().__init__(message or self.default_message)
        self.message = message or self.default_message
        self.detail = detail


class ValidationError(AppError):
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    default_message = "Validation failed."


class NotFoundError(AppError):
    status_code = HTTPStatus.NOT_FOUND
    default_message = "Resource not found."


class ConflictError(AppError):
    status_code = HTTPStatus.CONFLICT
    default_message = "Resource conflict."


class AuthenticationError(AppError):
    status_code = HTTPStatus.UNAUTHORIZED
    default_message = "Not authenticated."


class AuthorizationError(AppError):
    status_code = HTTPStatus.FORBIDDEN
    default_message = "Not permitted."


class RateLimitError(AppError):
    status_code = HTTPStatus.TOO_MANY_REQUESTS
    default_message = "Too many requests."


class ProviderNotConfiguredError(AppError):
    """A pluggable capability has no adapter selected for its provider."""

    status_code = HTTPStatus.NOT_IMPLEMENTED
    default_message = "Provider is not configured."


class SignatureVerificationError(AppError):
    """An inbound provider request did not carry a valid provider signature.

    The response is deliberately indistinguishable from a plain bad request: a
    rejected webhook must not reveal what a correct payload would have looked
    like.
    """

    status_code = HTTPStatus.BAD_REQUEST
    default_message = "Provider signature verification failed."


def status_for(error: AppError) -> int:
    """Resolve the HTTP status code for a given application error."""
    return int(error.status_code)
