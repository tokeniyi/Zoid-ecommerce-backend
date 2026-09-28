"""Session strategies.

A session maps an authenticated identity to a bearer token the browser can
present later. The concrete representation (here a signed JWT delivered via an
HTTP-only cookie) is hidden behind `AbstractSessionStrategy` so the strategy can
be swapped without the rest of the backend noticing — architecture section 7.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import jwt
from pydantic import ValidationError

from app.config import get_settings
from app.security.authentication.schemas import TokenPayload
from app.shared.exceptions import AuthenticationError

# Used only when no JWT_SECRET is configured (local development). Kept at 32+
# bytes to satisfy the HMAC key-length guidance. Production deployments must
# set JWT_SECRET; the composition root surfaces the fallback clearly.
_DEV_FALLBACK_SECRET = "dev-insecure-secret-change-me-in-production-please"


@dataclass(frozen=True)
class SessionClaims:
    """A verified session: the subject (user id), its role and its lifetime.

    The role is carried as a session claim so the backend can enforce
    authorization at the edge from a verified token, independently of the
    frontend. (Re-validating the role against the database is a later
    hardening concern.)
    """

    subject: str
    issued_at: int
    expires_at: int
    role: str = "customer"


class AbstractSessionStrategy(ABC):
    """Issue and verify opaque session tokens for a subject."""

    @abstractmethod
    def issue(self, subject: str, *, role: str = "customer") -> tuple[str, SessionClaims]:
        """Return ``(token, claims)`` for ``subject`` with the given ``role``."""

    @abstractmethod
    def verify(self, token: str) -> SessionClaims:
        """Return the `SessionClaims` for ``token`` or raise `AuthenticationError`."""


class JwtCookieSessionStrategy(AbstractSessionStrategy):
    """Stateless JWT (HS256 by default) delivered via a cookie.

    Signing/verification uses PyJWT; no other module depends on it.
    """

    def __init__(
        self,
        secret: str,
        *,
        algorithm: str = "HS256",
        ttl_minutes: int = 60 * 24 * 7,
    ) -> None:
        if not secret:
            raise ValueError("JWT secret must not be empty.")
        self._secret = secret
        self._algorithm = algorithm
        self._ttl_seconds = int(ttl_minutes * 60)

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    def issue(self, subject: str, *, role: str = "customer") -> tuple[str, SessionClaims]:
        now = int(time.time())
        expires_at = now + self._ttl_seconds
        token = jwt.encode(
            {"sub": subject, "iat": now, "exp": expires_at, "role": role},
            self._secret,
            algorithm=self._algorithm,
        )
        return token, SessionClaims(
            subject=subject, issued_at=now, expires_at=expires_at, role=role
        )

    def verify(self, token: str) -> SessionClaims:
        try:
            raw = jwt.decode(token, self._secret, algorithms=[self._algorithm])
            payload = TokenPayload(**raw)
        except (jwt.PyJWTError, ValidationError) as exc:
            raise AuthenticationError("Invalid or expired session.") from exc
        return SessionClaims(
            subject=payload.sub,
            issued_at=payload.iat,
            expires_at=payload.exp,
            role=payload.role,
        )


def session_strategy_from_settings() -> JwtCookieSessionStrategy:
    """Build the configured session strategy from environment settings."""
    settings = get_settings()
    return JwtCookieSessionStrategy(
        secret=settings.jwt_secret or _DEV_FALLBACK_SECRET,
        algorithm=settings.jwt_algorithm,
        ttl_minutes=settings.session_ttl_minutes,
    )
