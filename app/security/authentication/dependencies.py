"""FastAPI dependencies for the authentication capability.

These translate an incoming request into a verified session and, ultimately, a
current-user id. Routers depend on these rather than on any session library.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Request

from app.security.authentication.service import (
    SessionService,
    session_service_from_settings,
)
from app.security.authentication.session import (
    AbstractSessionStrategy,
    SessionClaims,
    session_strategy_from_settings,
)
from app.shared.exceptions import AuthenticationError


@lru_cache
def _session_service() -> SessionService:
    return session_service_from_settings()


@lru_cache
def _session_strategy() -> AbstractSessionStrategy:
    return session_strategy_from_settings()


def get_session_service() -> SessionService:
    """Provide the cookie-delivery service."""
    return _session_service()


def get_session_strategy() -> AbstractSessionStrategy:
    """Provide the configured session strategy."""
    return _session_strategy()


def get_current_session(request: Request) -> SessionClaims:
    """Resolve and verify the session from the request cookie.

    Raises `AuthenticationError` (HTTP 401) when no/invalid session is present.
    """
    token = _session_service().read_token(request)
    if not token:
        raise AuthenticationError("Not authenticated.")
    return _session_strategy().verify(token)


def get_current_user_id(request: Request) -> int:
    """Return the authenticated user's id from a valid session."""
    claims = get_current_session(request)
    try:
        return int(claims.subject)
    except ValueError as exc:
        raise AuthenticationError("Invalid session subject.") from exc
