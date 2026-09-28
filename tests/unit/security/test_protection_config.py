"""Protection primitives in isolation: CORS options, security headers and the
request-validation envelope. Deterministic, no networking.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.security.protection import configure_security_headers
from app.security.protection.cors import cors_middleware_options
from app.security.protection.request_validation import install_request_validation


def test_cors_options_are_configuration_driven() -> None:
    options = cors_middleware_options()
    assert "http://localhost:5173" in options["allow_origins"]
    assert isinstance(options["allow_credentials"], bool)


def test_security_headers_are_added_to_every_response() -> None:
    app = FastAPI()
    configure_security_headers(app)

    @app.get("/ping")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    response = TestClient(app).get("/ping")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_request_validation_returns_consistent_envelope() -> None:
    app = FastAPI()
    install_request_validation(app)

    @app.get("/needs-count")
    async def needs_count(count: int) -> dict[str, int]:
        return {"count": count}

    response = TestClient(app).get("/needs-count")  # missing required query param
    assert response.status_code == 422
    body = response.json()
    assert body["detail"] == "Request validation failed."
    assert isinstance(body["errors"], list) and body["errors"]
