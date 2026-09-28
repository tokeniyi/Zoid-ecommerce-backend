"""Guest and authenticated cart endpoints against the configured database.

Products are seeded via the repository (no public write endpoint); all cart
traffic goes through the real FastAPI app over the shared session-scoped client.
Guest carts are carried by the ``guest_cart_id`` cookie, authenticated carts by
the session cookie.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import get_settings
from app.domains.cart.api.deps import GUEST_CART_COOKIE
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
        slug=f"cart-jersey-{tag}",
        name=f"Cart Jersey {tag}",
        category=Category(id=0, name="Cart Curated", slug="cart-curated"),
        price=Decimal("25000.00"),
        images=[ProductImage(url="/front.jpg", view="front")],
        variants=[
            ProductVariant(id=0, sku=f"cart-{tag}-M", size="M", inventory=Inventory(quantity=20)),
            ProductVariant(id=0, sku=f"cart-{tag}-L", size="L", inventory=Inventory(quantity=20)),
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
    email = f"zoid-cart-{uuid4()}@example.com"
    signup = client.post(
        f"{API}/auth/signup",
        json={"name": "Bagger", "email": email, "password": PASSWORD},
    )
    assert signup.status_code == 201, signup.text
    login = client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return login.cookies.get(COOKIE)


def _add(
    client: TestClient,
    slug: str,
    *,
    size: str = "M",
    qty: int = 1,
    cookie: str | None = None,
):
    cookies = {GUEST_CART_COOKIE: cookie} if cookie else None
    return client.post(
        f"{API}/cart/items",
        json={"product_slug": slug, "size": size, "quantity": qty},
        cookies=cookies,
    )


async def test_guest_creates_cart_and_adds_item(client: TestClient) -> None:
    slug = await _product_slug()

    response = _add(client, slug, qty=2)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 2
    assert body["items"][0]["product_slug"] == slug
    assert body["items"][0]["unit_price"] == 25000.0
    guest_token = response.cookies.get(GUEST_CART_COOKIE)
    assert guest_token, "guest cart cookie should be issued"

    fetched = client.get(f"{API}/cart", cookies={GUEST_CART_COOKIE: guest_token})
    assert fetched.status_code == 200
    assert fetched.json()["count"] == 2


async def test_guest_adding_same_variant_increments(client: TestClient) -> None:
    slug = await _product_slug()
    first = _add(client, slug, qty=1)
    token = first.cookies.get(GUEST_CART_COOKIE)

    second = _add(client, slug, qty=3, cookie=token)

    assert second.json()["count"] == 4
    assert len(second.json()["items"]) == 1


async def test_guest_update_and_remove_item(client: TestClient) -> None:
    slug = await _product_slug()
    added = _add(client, slug, qty=1)
    token = added.cookies.get(GUEST_CART_COOKIE)
    item_id = added.json()["items"][0]["id"]

    updated = client.patch(
        f"{API}/cart/items/{item_id}",
        cookies={GUEST_CART_COOKIE: token},
        json={"quantity": 7},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["items"][0]["quantity"] == 7

    removed = client.delete(f"{API}/cart/items/{item_id}", cookies={GUEST_CART_COOKIE: token})
    assert removed.status_code == 200, removed.text
    assert removed.json()["items"] == []


async def test_authenticated_user_has_own_cart(client: TestClient) -> None:
    slug = await _product_slug()
    session = _register_and_login(client)

    added = client.post(
        f"{API}/cart/items",
        cookies={COOKIE: session},
        json={"product_slug": slug, "size": "L", "quantity": 2},
    )
    assert added.status_code == 200, added.text
    assert added.json()["count"] == 2
    # An authenticated response must not mint a guest cart cookie.
    assert added.cookies.get(GUEST_CART_COOKIE) is None

    fetched = client.get(f"{API}/cart", cookies={COOKIE: session})
    assert fetched.json()["items"][0]["size"] == "L"


async def test_guest_cart_is_not_the_authenticated_cart(client: TestClient) -> None:
    slug = await _product_slug()
    guest = _add(client, slug, qty=5).cookies.get(GUEST_CART_COOKIE)
    session = _register_and_login(client)

    # The same shopper, now authenticated, sees their own (empty) cart — the
    # guest bag is not exposed just because they logged in.
    mine = client.get(f"{API}/cart", cookies={COOKIE: session})

    assert mine.json()["count"] == 0
    assert guest is not None


async def test_merge_requires_authentication(client: TestClient) -> None:
    assert client.post(f"{API}/cart/merge").status_code == 401


async def test_merge_folds_guest_cart_into_user(client: TestClient) -> None:
    slug = await _product_slug()
    guest = _add(client, slug, qty=3).cookies.get(GUEST_CART_COOKIE)
    session = _register_and_login(client)

    merged = client.post(
        f"{API}/cart/merge",
        cookies={COOKIE: session, GUEST_CART_COOKIE: guest},
    )

    assert merged.status_code == 200, merged.text
    assert merged.json()["count"] == 3
    assert merged.json()["items"][0]["product_slug"] == slug

    # The user's cart now durably holds the merged line.
    mine = client.get(f"{API}/cart", cookies={COOKIE: session})
    assert mine.json()["count"] == 3
