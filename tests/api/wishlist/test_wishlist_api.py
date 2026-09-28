"""Wishlist endpoints against the configured database.

Products are seeded via the repository; wishlist traffic goes through the real
FastAPI app over the shared session-scoped client. The wishlist is authenticated
and scoped to the caller's session (never a path id).
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import get_settings
from app.domains.products.domain.entities import (
    Category,
    Inventory,
    Product,
    ProductImage,
    ProductVariant,
)
from app.infrastructure.persistence.sqlalchemy.session import (
    build_sessionmaker,
    create_engine_from_url,
)
from app.infrastructure.persistence.sqlalchemy.unit_of_work import SqlAlchemyUnitOfWork

_settings = get_settings()
API = _settings.api_v1_prefix
COOKIE = _settings.cookie_name
PASSWORD = "Sup3rSecret!"


def _make_product() -> Product:
    tag = uuid4().hex[:8]
    return Product(
        id=0,
        slug=f"wish-jersey-{tag}",
        name=f"Wish Jersey {tag}",
        category=Category(id=0, name="Wish Curated", slug="wish-curated"),
        price=Decimal("33000.00"),
        images=[ProductImage(url="/front.jpg", view="front")],
        variants=[
            ProductVariant(id=0, sku=f"wish-{tag}-M", size="M", inventory=Inventory(quantity=10)),
        ],
    )


async def _seed(product: Product) -> Product:
    engine = create_engine_from_url()
    try:
        async with SqlAlchemyUnitOfWork(build_sessionmaker(engine)) as uow:
            created = await uow.products.add(product)
            await uow.commit()
            return created
    finally:
        await engine.dispose()


async def _product_slug() -> str:
    return (await _seed(_make_product())).slug


def _register_and_login(client: TestClient) -> str:
    email = f"zoid-wish-{uuid4()}@example.com"
    signup = client.post(
        f"{API}/auth/signup",
        json={"name": "Wisher", "email": email, "password": PASSWORD},
    )
    assert signup.status_code == 201, signup.text
    login = client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return login.cookies.get(COOKIE)


def _add(client: TestClient, session: str, slug: str):
    return client.post(
        f"{API}/wishlist/items",
        cookies={COOKIE: session},
        json={"product_slug": slug},
    )


async def test_wishlist_requires_authentication(client: TestClient) -> None:
    assert client.get(f"{API}/wishlist").status_code == 401
    assert client.post(f"{API}/wishlist/items", json={"product_slug": "x"}).status_code == 401


async def test_add_list_and_remove_flow(client: TestClient) -> None:
    slug = await _product_slug()
    session = _register_and_login(client)

    added = _add(client, session, slug)
    assert added.status_code == 200, added.text
    assert added.json()["count"] == 1
    assert added.json()["items"][0]["product_slug"] == slug
    assert added.json()["items"][0]["price"] == 33000.0

    listed = client.get(f"{API}/wishlist", cookies={COOKIE: session})
    assert listed.json()["count"] == 1

    removed = client.delete(f"{API}/wishlist/items/{slug}", cookies={COOKIE: session})
    assert removed.status_code == 200, removed.text
    assert removed.json()["count"] == 0

    after = client.get(f"{API}/wishlist", cookies={COOKIE: session})
    assert after.json()["count"] == 0


async def test_add_is_idempotent_over_http(client: TestClient) -> None:
    slug = await _product_slug()
    session = _register_and_login(client)

    _add(client, session, slug)
    again = _add(client, session, slug)

    assert again.json()["count"] == 1


async def test_add_unknown_product_returns_404(client: TestClient) -> None:
    session = _register_and_login(client)

    response = _add(client, session, f"does-not-exist-{uuid4().hex}")

    assert response.status_code == 404, response.text


async def test_remove_not_saved_returns_404(client: TestClient) -> None:
    session = _register_and_login(client)

    response = client.delete(f"{API}/wishlist/items/never-added", cookies={COOKIE: session})

    assert response.status_code == 404, response.text


async def test_wishlists_are_isolated_per_user(client: TestClient) -> None:
    slug = await _product_slug()
    session_a = _register_and_login(client)
    session_b = _register_and_login(client)

    assert _add(client, session_a, slug).status_code == 200

    # User B neither sees nor can remove user A's saved product.
    b_list = client.get(f"{API}/wishlist", cookies={COOKIE: session_b})
    assert b_list.json()["count"] == 0

    b_remove = client.delete(f"{API}/wishlist/items/{slug}", cookies={COOKIE: session_b})
    assert b_remove.status_code == 404

    a_list = client.get(f"{API}/wishlist", cookies={COOKIE: session_a})
    assert a_list.json()["count"] == 1
