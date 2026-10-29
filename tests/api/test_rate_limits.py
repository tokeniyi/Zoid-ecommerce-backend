"""Rate limits on the production routes, exercised through the real app.

Every test builds its app with ``create_app()`` and a limiter driven by a fake
clock, so the window is crossed by advancing time rather than by sleeping. The
``rate_limits_enabled`` fixture switches limiting on for one test and installs
a fresh limiter, so no counter survives into the next test.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.security.protection.rate_limiter import InMemoryRateLimiter, use_rate_limiter
from tests.support.clock import FakeClock

pytestmark = pytest.mark.database

API = get_settings().api_v1_prefix
LOGIN = f"{API}/auth/login"
SIGNUP = f"{API}/auth/signup"
WRONG_LOGIN = {"email": "nobody@zoid.example", "password": "wrong-password"}


@pytest.fixture
def clock(rate_limits_enabled: None) -> FakeClock:
    clock = FakeClock()
    use_rate_limiter(InMemoryRateLimiter(time_source=clock))
    return clock


@pytest.fixture
def app_client(clock: FakeClock) -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app()) as client:
        yield client


def _signup(client: TestClient, n: int) -> int:
    body = {"name": "Rate", "email": f"rate{n}@zoid.example", "password": "a-long-password"}
    return client.post(SIGNUP, json=body).status_code


def test_login_allows_five_per_minute_then_returns_429(app_client: TestClient) -> None:
    for _ in range(5):
        assert app_client.post(LOGIN, json=WRONG_LOGIN).status_code == 401

    blocked = app_client.post(LOGIN, json=WRONG_LOGIN)
    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "Too many requests."}


def test_signup_allows_five_per_minute_then_returns_429(app_client: TestClient) -> None:
    assert [_signup(app_client, n) for n in range(5)] == [201] * 5
    assert _signup(app_client, 5) == 429


def test_login_window_resets_after_a_minute(app_client: TestClient, clock: FakeClock) -> None:
    for _ in range(5):
        app_client.post(LOGIN, json=WRONG_LOGIN)
    assert app_client.post(LOGIN, json=WRONG_LOGIN).status_code == 429

    clock.advance(59)
    assert app_client.post(LOGIN, json=WRONG_LOGIN).status_code == 429

    clock.advance(2)
    assert app_client.post(LOGIN, json=WRONG_LOGIN).status_code == 401


@pytest.mark.parametrize("path", ["/payments/initiate", "/payments/verify"])
def test_payment_routes_allow_sixty_per_minute_then_return_429(
    app_client: TestClient, path: str
) -> None:
    # Limiting runs before authentication, so anonymous calls count too.
    for _ in range(60):
        assert app_client.post(f"{API}{path}", json={}).status_code == 401
    assert app_client.post(f"{API}{path}", json={}).status_code == 429


def test_limits_are_counted_per_route(app_client: TestClient) -> None:
    for _ in range(5):
        app_client.post(LOGIN, json=WRONG_LOGIN)
    assert app_client.post(LOGIN, json=WRONG_LOGIN).status_code == 429
    assert _signup(app_client, 0) == 201


def test_payment_webhooks_are_not_rate_limited(app_client: TestClient) -> None:
    statuses = {
        app_client.post(f"{API}/payments/webhooks/paystack", content=b"{}").status_code
        for _ in range(100)
    }
    assert 429 not in statuses


def test_forwarded_for_header_is_not_trusted_by_default(app_client: TestClient) -> None:
    for n in range(5):
        headers = {"X-Forwarded-For": f"203.0.113.{n}"}
        assert app_client.post(LOGIN, json=WRONG_LOGIN, headers=headers).status_code == 401

    headers = {"X-Forwarded-For": "203.0.113.99"}
    assert app_client.post(LOGIN, json=WRONG_LOGIN, headers=headers).status_code == 429


def test_rate_limit_enabled_false_turns_limiting_off(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()

    assert [app_client.post(LOGIN, json=WRONG_LOGIN).status_code for _ in range(10)] == [401] * 10
