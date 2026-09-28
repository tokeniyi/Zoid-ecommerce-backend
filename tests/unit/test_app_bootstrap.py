"""The FastAPI application imports and boots; health endpoint responds."""

from fastapi.testclient import TestClient

from app.main import app, create_app


def test_application_imports_singleton() -> None:
    assert app is not None
    assert app.title  # settings-driven title is present


def test_health_endpoint_returns_ok() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
