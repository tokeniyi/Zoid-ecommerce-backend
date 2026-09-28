"""Session strategy + cookie-delivery tests.

Covers issue/verify, tamper/expiry rejection (invalid-session behaviour) and the
HTTP cookie set/clear mechanics — all behind the session abstraction.
"""

from __future__ import annotations

import pytest
from starlette.responses import Response

from app.security.authentication.service import SessionService
from app.security.authentication.session import JwtCookieSessionStrategy
from app.shared.exceptions import AuthenticationError

# Realistic-length secrets so PyJWT does not warn about short HMAC keys.
SECRET_A = "secret-key-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SECRET_B = "secret-key-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def _set_cookie_headers(response: Response) -> list[str]:
    return [
        value.decode()
        for key, value in response.raw_headers
        if key.lower() == b"set-cookie"
    ]


def test_issue_and_verify_roundtrip() -> None:
    strategy = JwtCookieSessionStrategy(secret=SECRET_A, ttl_minutes=60)
    token, claims = strategy.issue("42")
    assert claims.subject == "42"
    verified = strategy.verify(token)
    assert verified.subject == "42"
    assert verified.expires_at > verified.issued_at


def test_token_does_not_leak_subject() -> None:
    strategy = JwtCookieSessionStrategy(secret=SECRET_A)
    token, _ = strategy.issue("supersecret-id")
    assert "supersecret-id" not in token


def test_verify_rejects_garbage_token() -> None:
    strategy = JwtCookieSessionStrategy(secret=SECRET_A)
    with pytest.raises(AuthenticationError):
        strategy.verify("not-a-jwt")


def test_verify_rejects_token_signed_with_another_secret() -> None:
    issuer = JwtCookieSessionStrategy(secret=SECRET_A)
    token, _ = issuer.issue("1")
    other = JwtCookieSessionStrategy(secret=SECRET_B)
    with pytest.raises(AuthenticationError):
        other.verify(token)


def test_verify_rejects_expired_token() -> None:
    strategy = JwtCookieSessionStrategy(secret=SECRET_A, ttl_minutes=-1)
    token, _ = strategy.issue("1")
    with pytest.raises(AuthenticationError):
        strategy.verify(token)


def test_empty_secret_is_rejected() -> None:
    with pytest.raises(ValueError):
        JwtCookieSessionStrategy(secret="")


def test_session_service_sets_and_clears_cookie() -> None:
    service = SessionService(cookie_name="app_session_id", secure=False, max_age=120)

    response = Response()
    service.set_cookie(response, "issued-token")
    cookies = _set_cookie_headers(response)
    assert any("app_session_id=issued-token" in c and "HttpOnly" in c for c in cookies)

    cleared = Response()
    service.clear_cookie(cleared)
    cleared_cookies = _set_cookie_headers(cleared)
    assert any(c.startswith("app_session_id=") and "Max-Age=0" in c for c in cleared_cookies)
