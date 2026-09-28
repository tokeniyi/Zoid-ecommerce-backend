"""Endpoint protection: rate limiting, CORS, security headers, validation.

`configure_protection` installs the transport-level guards on the app in one
call; individual routers never re-implement them.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.security.protection.cors import configure_cors, cors_middleware_options
from app.security.protection.headers import configure_security_headers
from app.security.protection.rate_limiter import (
    InMemoryRateLimiter,
    RateLimiter,
    client_ip,
    rate_limit,
)
from app.security.protection.request_validation import install_request_validation


def configure_protection(app: FastAPI) -> None:
    """Install CORS, security headers and request-validation handling."""
    configure_cors(app)
    configure_security_headers(app)
    install_request_validation(app)


__all__ = [
    "configure_protection",
    "configure_cors",
    "cors_middleware_options",
    "configure_security_headers",
    "install_request_validation",
    "RateLimiter",
    "InMemoryRateLimiter",
    "rate_limit",
    "client_ip",
]
