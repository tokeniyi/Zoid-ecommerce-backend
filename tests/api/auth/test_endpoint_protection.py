"""Proves the backend independently enforces auth/authz at the endpoint edge.

Uses the real session strategy and the reusable authorization/protection
dependencies against a minimal app (production placeholder routes are not the
concern here — the guards are).
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.config import get_settings
from app.security.authentication.session import session_strategy_from_settings
from app.security.authorization import (
    AbstractRoleSource,
    Permission,
    Principal,
    get_role_source,
    require_admin,
    require_authenticated_user,
    require_permission,
)
from app.security.protection import InMemoryRateLimiter, rate_limit
from app.shared.exceptions import AppError, status_for

# Tokens minted with the same strategy/secret the dependencies derive from
# settings, so they verify in-process.
_strategy = session_strategy_from_settings()
CUSTOMER_TOKEN = _strategy.issue("7", role="customer")[0]
ADMIN_TOKEN = _strategy.issue("1", role="admin")[0]
#: User 2's token was issued while they were an admin; the store has since
#: demoted them. User 3's token is for someone who no longer exists.
DEMOTED_TOKEN = _strategy.issue("2", role="admin")[0]
DELETED_TOKEN = _strategy.issue("3", role="admin")[0]


class _StoredRoles(AbstractRoleSource):
    """The roles the store holds now, standing in for the users table."""

    roles = {1: "admin", 2: "customer", 7: "customer"}

    async def current_role(self, user_id: int) -> str | None:
        return self.roles.get(user_id)


def _build_app(*, wire_roles: bool = True) -> FastAPI:
    app = FastAPI()
    if wire_roles:
        app.dependency_overrides[get_role_source] = _StoredRoles

    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=status_for(exc), content={"detail": exc.message})

    @app.get("/public")
    async def public() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/protected")
    async def protected(
        principal: Principal = Depends(require_authenticated_user),
    ) -> dict[str, object]:
        return {"user_id": principal.user_id, "role": principal.role.value}

    @app.get("/admin")
    async def admin(principal: Principal = Depends(require_admin)) -> dict[str, int]:
        return {"user_id": principal.user_id}

    @app.get("/needs-products")
    async def needs_products(
        _: Principal = Depends(require_permission(Permission.MANAGE_PRODUCTS)),
    ) -> dict[str, bool]:
        return {"granted": True}

    @app.get("/limited", dependencies=[Depends(rate_limit(limit=2, limiter=InMemoryRateLimiter()))])
    async def limited() -> dict[str, bool]:
        return {"ok": True}

    return app


def _client(token: str | None = None, *, wire_roles: bool = True) -> TestClient:
    client = TestClient(_build_app(wire_roles=wire_roles))
    if token is not None:
        client.cookies.set(get_settings().cookie_name, token)
    return client


def test_public_route_is_accessible_without_authentication() -> None:
    assert _client().get("/public").status_code == 200


def test_unauthenticated_protected_request_returns_401() -> None:
    assert _client().get("/protected").status_code == 401


def test_invalid_session_token_returns_401() -> None:
    assert _client(token="not-a-real-token").get("/protected").status_code == 401


def test_authenticated_customer_can_access_protected_route() -> None:
    response = _client(token=CUSTOMER_TOKEN).get("/protected")
    assert response.status_code == 200
    assert response.json() == {"user_id": 7, "role": "customer"}


def test_authenticated_non_admin_is_forbidden_from_admin_route() -> None:
    assert _client(token=CUSTOMER_TOKEN).get("/admin").status_code == 403


def test_authorized_admin_can_access_admin_route() -> None:
    response = _client(token=ADMIN_TOKEN).get("/admin")
    assert response.status_code == 200
    assert response.json() == {"user_id": 1}


def test_permission_guard_blocks_customer_and_allows_admin() -> None:
    assert _client(token=CUSTOMER_TOKEN).get("/needs-products").status_code == 403
    assert _client(token=ADMIN_TOKEN).get("/needs-products").status_code == 200


def test_admin_guard_uses_the_stored_role_not_the_token_claim() -> None:
    assert _client(token=DEMOTED_TOKEN).get("/admin").status_code == 403
    assert _client(token=DEMOTED_TOKEN).get("/needs-products").status_code == 403


def test_admin_guard_refuses_a_user_who_no_longer_exists() -> None:
    assert _client(token=DELETED_TOKEN).get("/admin").status_code == 401
    assert _client(token=DELETED_TOKEN).get("/needs-products").status_code == 401


def test_customer_routes_need_only_a_verified_session() -> None:
    """The stored-role lookup is for privileged guards; it is not consulted here."""
    response = _client(token=CUSTOMER_TOKEN, wire_roles=False).get("/protected")
    assert response.status_code == 200


def test_privileged_guards_fail_closed_when_no_role_source_is_wired() -> None:
    """Without a role source the guard errors; it never falls back to the claim."""
    with pytest.raises(RuntimeError, match="No role source is wired"):
        _client(token=ADMIN_TOKEN, wire_roles=False).get("/admin")


def test_rate_limit_enforces_boundary_without_timing() -> None:
    client = _client()
    assert client.get("/limited").status_code == 200
    assert client.get("/limited").status_code == 200
    assert client.get("/limited").status_code == 429
