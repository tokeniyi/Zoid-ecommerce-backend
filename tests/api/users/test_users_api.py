"""End-to-end self-service profile tests against the configured database.

Exercises the real FastAPI app (auth + users routers, JWT cookie sessions,
SQLAlchemy persistence). A single module-scoped ``TestClient`` is shared so the
async engine lives on one event loop for the whole module.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from tests.support.cookies import with_cookies

pytestmark = pytest.mark.database

_settings = get_settings()
API = _settings.api_v1_prefix
COOKIE = _settings.cookie_name
PASSWORD = "Sup3rSecret!"


def _register_and_login(client: TestClient) -> tuple[str, str]:
    """Create a fresh account and return ``(email, session_token)``."""
    email = f"zoid-user-{uuid4()}@example.com"
    signup = client.post(
        f"{API}/auth/signup",
        json={"name": "Test User", "email": email, "password": PASSWORD},
    )
    assert signup.status_code == 201, signup.text

    login = client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    token = login.cookies.get(COOKIE)
    assert token, "login should set the session cookie"
    return email, token


def test_me_requires_authentication(client: TestClient) -> None:
    assert client.get(f"{API}/users/me").status_code == 401


def test_get_own_profile(client: TestClient) -> None:
    email, token = _register_and_login(client)

    response = with_cookies(client, {COOKIE: token}).get(f"{API}/users/me")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["email"] == email
    assert body["role"] == "customer"


def test_update_own_profile_persists(client: TestClient) -> None:
    _, token = _register_and_login(client)

    updated = with_cookies(client, {COOKIE: token}).put(
        f"{API}/users/me",
        json={"name": "Renamed", "phone": "+15550001111"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Renamed"
    assert updated.json()["phone"] == "+15550001111"

    # The change is durable, not just echoed.
    fetched = with_cookies(client, {COOKIE: token}).get(f"{API}/users/me")
    assert fetched.json()["name"] == "Renamed"


def test_one_user_cannot_alter_another_profile(client: TestClient) -> None:
    email_a, token_a = _register_and_login(client)
    email_b, token_b = _register_and_login(client)

    victim_before = with_cookies(client, {COOKIE: token_b}).get(f"{API}/users/me").json()

    # A edits their own profile. There is no target id on the route, so A can
    # only ever touch A's record.
    edited = with_cookies(client, {COOKIE: token_a}).put(
        f"{API}/users/me",
        json={"name": "Only Alice", "phone": "+10000000000"},
    )
    assert edited.status_code == 200

    victim_after = with_cookies(client, {COOKIE: token_b}).get(f"{API}/users/me").json()

    assert victim_after["email"] == email_b
    assert victim_after["name"] == victim_before["name"]  # unchanged by A
    assert victim_after["name"] != "Only Alice"
