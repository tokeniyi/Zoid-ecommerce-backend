"""Real user accounts for API tests, including administrators.

There is no endpoint that grants the admin role (by design), so a test that
needs an administrator signs a customer up through the API and then promotes
the row in the test database, the way an operator would. Its session comes from
the real login endpoint afterwards, so nothing about the token is invented.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import get_settings
from app.infrastructure.persistence.sqlalchemy.session import create_engine_from_url

PASSWORD = "Sup3rSecret!"


async def _execute(statement: str, **params: object) -> int:
    engine = create_engine_from_url()
    try:
        async with engine.begin() as connection:
            result = await connection.execute(text(statement), params)
            return result.rowcount
    finally:
        await engine.dispose()


async def set_role(user_id: int, role: str) -> None:
    """Change ``user_id``'s role in the database (``role`` must be a seeded role)."""
    changed = await _execute(
        "UPDATE users SET role_id = (SELECT id FROM roles WHERE name = :role) WHERE id = :user_id",
        role=role,
        user_id=user_id,
    )
    assert changed == 1, f"user {user_id} not found"


async def delete_user(user_id: int) -> None:
    """Remove ``user_id`` from the database (dependent rows cascade)."""
    deleted = await _execute("DELETE FROM users WHERE id = :user_id", user_id=user_id)
    assert deleted == 1, f"user {user_id} not found"


def signup(client: TestClient, *, prefix: str = "zoid-user") -> tuple[str, int]:
    """Register a customer through the API: returns ``(email, user id)``."""
    email = f"{prefix}-{uuid4()}@example.com"
    response = client.post(
        f"{get_settings().api_v1_prefix}/auth/signup",
        json={"name": "Buyer", "email": email, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    return email, int(response.json()["id"])


def login(client: TestClient, email: str) -> str:
    """Log in through the API and return the session token it set."""
    settings = get_settings()
    response = client.post(
        f"{settings.api_v1_prefix}/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    token = response.cookies.get(settings.cookie_name)
    assert token, "login set no session cookie"
    return str(token)


async def register_admin(client: TestClient) -> tuple[str, int]:
    """A real administrator: signed up, promoted in the database, then logged in.

    Returns ``(session token, user id)``. The token is the one the login
    endpoint issued after the promotion.
    """
    email, user_id = signup(client, prefix="zoid-admin")
    await set_role(user_id, "admin")
    return login(client, email), user_id
