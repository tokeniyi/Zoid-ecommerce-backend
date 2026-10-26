"""The real application, as `create_app()` assembles it, boots and is protected.

The protection primitives are tested in isolation elsewhere on throwaway apps;
these tests prove the production factory actually installs them. None of them
touch the database: every request is answered before a repository is used.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.security.protection.headers import SECURITY_HEADERS

API = get_settings().api_v1_prefix


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


def test_health_reports_the_configured_service(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": get_settings().app_name}


def test_every_response_carries_the_security_headers(client: TestClient) -> None:
    response = client.get("/health")

    for header, value in SECURITY_HEADERS.items():
        assert response.headers.get(header) == value, header


def test_a_configured_origin_may_call_the_api_with_credentials(client: TestClient) -> None:
    origin = get_settings().cors_origin_list[0]

    response = client.options(
        f"{API}/products",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_an_unlisted_origin_is_not_granted_access(client: TestClient) -> None:
    origin = "https://not-zoid.example"
    assert origin not in get_settings().cors_origin_list

    response = client.options(
        f"{API}/products",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_malformed_input_to_a_real_route_gets_the_validation_envelope(
    client: TestClient,
) -> None:
    response = client.post(f"{API}/auth/login", json={})

    assert response.status_code == 422
    body = response.json()
    assert body["detail"] == "Request validation failed."
    missing = {tuple(error["loc"]) for error in body["errors"]}
    assert ("body", "email") in missing
    assert ("body", "password") in missing


def test_a_domain_error_from_a_real_route_gets_the_error_envelope(
    client: TestClient,
) -> None:
    response = client.get(f"{API}/auth/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated."}
