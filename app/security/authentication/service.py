"""HTTP cookie delivery for sessions.

This is the only place that touches the response/request cookie mechanics. The
token itself is produced and validated by a session strategy; here we merely
transport it to and from the browser as a secure, HTTP-only cookie.
"""

from __future__ import annotations

from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import Response

from app.config import get_settings


@dataclass(frozen=True)
class SessionService:
    """Sets, clears and reads the authentication cookie on HTTP transports."""

    cookie_name: str
    secure: bool = True
    httponly: bool = True
    samesite: str = "lax"
    domain: str = ""
    max_age: int = 60 * 60 * 24 * 7

    def read_token(self, request: Request) -> str | None:
        """Return the raw session token from the request cookie, if present."""
        return request.cookies.get(self.cookie_name)

    def set_cookie(self, response: Response, token: str) -> None:
        """Attach the session cookie to an outgoing response."""
        response.set_cookie(
            key=self.cookie_name,
            value=token,
            max_age=self.max_age,
            path="/",
            domain=self.domain or None,
            secure=self.secure,
            httponly=self.httponly,
            samesite=self.samesite,  # type: ignore[arg-type]
        )

    def clear_cookie(self, response: Response) -> None:
        """Invalidate the session on the client by removing the cookie."""
        response.delete_cookie(
            key=self.cookie_name,
            path="/",
            domain=self.domain or None,
        )


def session_service_from_settings() -> SessionService:
    """Build the cookie-delivery service from environment settings."""
    settings = get_settings()
    return SessionService(
        cookie_name=settings.cookie_name,
        secure=settings.cookie_secure,
        httponly=settings.cookie_httponly,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        max_age=settings.session_ttl_minutes * 60,
    )
