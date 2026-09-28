"""Proves the backend independently enforces auth/authz at the endpoint edge.

Uses the real session strategy and the reusable authorization/protection
dependencies against a minimal app (production placeholder routes are not the
concern here — the guards are).
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.config import get_settings
from app.security.authentication.session import session_strategy_from_settings
from app.security.authorization import (
    Permission,
    Principal,
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


def _build_app() -> FastAPI:
    app = FastAPI()

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


def _client(token: str | None = None) -> TestClient:
    client = TestClient(_build_app())
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


def test_rate_limit_enforces_boundary_without_timing() -> None:
    client = _client()
    assert client.get("/limited").status_code == 200
    assert client.get("/limited").status_code == 200
    assert client.get("/limited").status_code == 429
