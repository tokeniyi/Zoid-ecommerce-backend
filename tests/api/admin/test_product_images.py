"""POST /admin/products/images through the real app, with a recording file store."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.domains.admin.application.images import ProductImageService
from app.infrastructure.container import get_product_image_service
from app.main import app
from app.security.authentication.session import session_strategy_from_settings
from tests.unit.admin.test_product_images import GIF, JPEG, PNG, WEBP, RecordingStore

_settings = get_settings()
API = _settings.api_v1_prefix
COOKIE = _settings.cookie_name
URL = f"{API}/admin/products/images"
CDN = "https://cdn.example.org"


def _admin() -> dict[str, str]:
    return {COOKIE: session_strategy_from_settings().issue("1", role="admin")[0]}


@pytest.fixture
def store(client: TestClient) -> Iterator[RecordingStore]:
    """Point the app's image service at a store that records what it is given."""
    recording = RecordingStore()
    app.dependency_overrides[get_product_image_service] = lambda: ProductImageService(
        storage=recording, public_base_url=CDN, max_bytes=1000
    )
    yield recording
    app.dependency_overrides.pop(get_product_image_service, None)


def _post(client: TestClient, body: bytes, *, content_type: str = "application/octet-stream"):
    return client.post(
        URL, content=body, cookies=_admin(), headers={"content-type": content_type}
    )


@pytest.mark.parametrize(
    ("body", "content_type", "extension"),
    [(JPEG, "image/jpeg", "jpg"), (PNG, "image/png", "png"),
     (GIF, "image/gif", "gif"), (WEBP, "image/webp", "webp")],
)
def test_an_admin_uploads_an_image_and_gets_its_public_url(
    client: TestClient, store: RecordingStore, body: bytes, content_type: str, extension: str
) -> None:
    response = _post(client, body, content_type=content_type)

    assert response.status_code == 201, response.text
    result = response.json()
    assert result["content_type"] == content_type and result["size"] == len(body)
    assert result["key"].startswith("products/") and result["key"].endswith(f".{extension}")
    assert result["url"] == f"{CDN}/{result['key']}"
    assert store.uploads[0].content == body


def test_the_files_contents_decide_not_what_the_browser_claims(
    client: TestClient, store: RecordingStore
) -> None:
    html = _post(client, b"<html><script>alert(1)</script></html>", content_type="image/jpeg")
    real = _post(client, PNG, content_type="text/plain")  # a real PNG with the wrong label

    assert html.status_code == 422 and "JPEG, PNG, GIF and WebP" in html.text
    assert real.status_code == 201 and real.json()["content_type"] == "image/png"
    assert len(store.uploads) == 1  # the page never reached the store


def test_empty_and_oversized_bodies_are_refused(client: TestClient, store: RecordingStore) -> None:
    assert _post(client, b"").status_code == 422
    too_big = _post(client, JPEG + b"\x00" * 2000)  # the fixture caps uploads at 1000 bytes
    assert too_big.status_code == 422 and "too large" in too_big.text
    assert store.uploads == []


def test_a_store_that_says_no_is_a_bad_gateway_not_a_crash(client: TestClient) -> None:
    from app.integrations.storage.contract import StoredFile

    failing = RecordingStore(StoredFile(success=False, message="credentials rejected"))
    app.dependency_overrides[get_product_image_service] = lambda: ProductImageService(
        storage=failing, public_base_url=CDN
    )
    try:
        response = _post(client, JPEG)
    finally:
        app.dependency_overrides.pop(get_product_image_service, None)

    assert response.status_code == 502
    assert "credentials rejected" in response.text


def test_only_an_admin_can_upload(client: TestClient, store: RecordingStore) -> None:
    customer = session_strategy_from_settings().issue("7", role="customer")[0]

    assert client.post(URL, content=JPEG).status_code == 401
    assert client.post(URL, content=JPEG, cookies={COOKIE: customer}).status_code == 403
    assert store.uploads == []


@pytest.mark.database
@pytest.mark.usefixtures("basic_delivery_rates")
async def test_an_uploaded_image_becomes_a_products_picture(
    client: TestClient, store: RecordingStore
) -> None:
    url = _post(client, JPEG, content_type="image/jpeg").json()["url"]
    tag = uuid4().hex[:8]

    created = client.post(
        f"{API}/admin/products", cookies=_admin(),
        json={"slug": f"photo-{tag}", "name": f"Photo Jersey {tag}", "category_slug": "photos",
              "category_name": "Photos", "price": "40000.00",
              "sizes": [{"size": "M", "quantity": 3}], "images": [{"url": url, "view": "front"}]},
    )

    assert created.status_code == 201, created.text
    assert client.get(f"{API}/products/photo-{tag}").json()["gallery"][0]["url"] == url
