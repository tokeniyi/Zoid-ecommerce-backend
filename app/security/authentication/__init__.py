"""Authentication capability: session strategies and request dependencies.

The rest of the backend never learns how a session is represented; it consumes
the current user through the dependencies exposed here.
"""

from app.security.authentication.dependencies import (
    get_current_session,
    get_current_user_id,
    get_session_service,
)
from app.security.authentication.service import SessionService
from app.security.authentication.session import (
    AbstractSessionStrategy,
    JwtCookieSessionStrategy,
    SessionClaims,
)

__all__ = [
    "AbstractSessionStrategy",
    "JwtCookieSessionStrategy",
    "SessionClaims",
    "SessionService",
    "get_current_session",
    "get_current_user_id",
    "get_session_service",
]
