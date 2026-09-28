"""Security headers.

A single middleware stamps conservative defaults on every response so no route
has to remember them. HSTS is added only when the deployment is configured to
serve cookies over HTTPS (i.e. real/production traffic).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import get_settings

SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Cache-Control": "no-store",
}

_HSTS_HEADER = "Strict-Transport-Security"
_HSTS_VALUE = "max-age=31536000; includeSubDomains"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        if get_settings().cookie_secure:
            response.headers.setdefault(_HSTS_HEADER, _HSTS_VALUE)
        return response


def configure_security_headers(app: FastAPI) -> None:
    """Install the security-headers middleware."""
    app.add_middleware(SecurityHeadersMiddleware)
