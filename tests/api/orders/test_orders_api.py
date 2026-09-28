"""Orders endpoints against the configured database.

The full checkout path is exercised over HTTP: seed a product, fill the caller's
server-side cart through the cart API, then place the order. Orders belong to
the session identity only, so another user's order simply is not found.
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
PRICE = Decimal("42000.00")

CHECKOUT = {
    "contact_name": "Ada Zoid",
    "contact_email": "ada@example.com",
    "contact_phone": "+234 800 000 0000",
    "address_line": "12 Concrete Road, Yaba",
    "city_state": "Lagos State",
    "notes": "Leave with the porter",
}


def _make_product(*, stock: int = 10) -> Product:
    tag = uuid4().hex[:8]
    return Product(
        id=0,
        slug=f"order-jersey-{tag}",
        name=f"Order Jersey {tag}",
        category=Category(id=0, name="Order Curated", slug="order-curated"),
        price=PRICE,
        images=[ProductImage(url="/front.jpg", view="front")],
        variants=[
            ProductVariant(
                id=0, sku=f"order-{tag}-M", size="M", inventory=Inventory(quantity=stock)
            ),
        ],
    )


async def _seed_product(*, stock: int = 10) -> str:
    product = _make_product(stock=stock)
    engine = create_engine_from_url()
    try:
        async with SqlAlchemyUnitOfWork(build_sessionmaker(engine)) as uow:
            created = await uow.products.add(product)
            await uow.commit()
            return created.slug
    finally:
        await engine.dispose()


def _register_and_login(client: TestClient) -> str:
    email = f"zoid-order-{uuid4()}@example.com"
    signup = client.post(
        f"{API}/auth/signup",
        json={"name": "Buyer", "email": email, "password": PASSWORD},
    )
    assert signup.status_code == 201, signup.text
    login = client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return login.cookies.get(COOKIE)


def _add_to_cart(client: TestClient, session: str, slug: str, *, quantity: int = 1):
    return client.post(
        f"{API}/cart/items",
        cookies={COOKIE: session},
        json={"product_slug": slug, "size": "M", "quantity": quantity},
    )


def _checkout(client: TestClient, session: str, **overrides: object):
    return client.post(f"{API}/orders", cookies={COOKIE: session}, json={**CHECKOUT, **overrides})


async def test_orders_require_authentication(client: TestClient) -> None:
    assert client.get(f"{API}/orders").status_code == 401
    assert client.post(f"{API}/orders", json=CHECKOUT).status_code == 401


async def test_checkout_creates_pending_payment_order(client: TestClient) -> None:
    slug = await _seed_product()
    session = _register_and_login(client)
    assert _add_to_cart(client, session, slug, quantity=2).status_code == 200

    response = _checkout(client, session)

    assert response.status_code == 201, response.text
    order = response.json()
    # Created as unpaid: success here never means "paid".
    assert order["status"] == "PENDING_PAYMENT"
    assert order["reference"].startswith("ZD-")
    assert order["total"] == float(PRICE) * 2
    assert order["count"] == 2
    assert order["contact_email"] == CHECKOUT["contact_email"]
    assert order["notes"] == CHECKOUT["notes"]
    line = order["items"][0]
    assert (line["product_slug"], line["size"], line["quantity"]) == (slug, "M", 2)
    assert line["unit_price"] == float(PRICE)
    assert line["line_total"] == float(PRICE) * 2

    fetched = client.get(f"{API}/orders/{order['id']}", cookies={COOKIE: session})
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["reference"] == order["reference"]

    listed = client.get(f"{API}/orders", cookies={COOKIE: session})
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [order["id"]]
    assert listed.json()[0]["status"] == "PENDING_PAYMENT"

    # The cart was consumed by the order.
    cart = client.get(f"{API}/cart", cookies={COOKIE: session})
    assert cart.json()["count"] == 0


async def test_orders_are_private_to_their_owner(client: TestClient) -> None:
    slug = await _seed_product()
    session_a = _register_and_login(client)
    session_b = _register_and_login(client)
    _add_to_cart(client, session_a, slug)
    order_id = _checkout(client, session_a).json()["id"]

    assert client.get(f"{API}/orders/{order_id}", cookies={COOKIE: session_b}).status_code == 404
    assert client.get(f"{API}/orders", cookies={COOKIE: session_b}).json() == []
    assert len(client.get(f"{API}/orders", cookies={COOKIE: session_a}).json()) == 1


async def test_empty_cart_cannot_be_ordered(client: TestClient) -> None:
    session = _register_and_login(client)

    response = _checkout(client, session)

    assert response.status_code == 422, response.text


async def test_insufficient_stock_blocks_checkout(client: TestClient) -> None:
    slug = await _seed_product(stock=2)
    session = _register_and_login(client)
    assert _add_to_cart(client, session, slug, quantity=3).status_code == 200

    response = _checkout(client, session)

    assert response.status_code == 409, response.text
    # Nothing was ordered and the cart is intact for the customer to fix.
    assert client.get(f"{API}/orders", cookies={COOKIE: session}).json() == []
    assert client.get(f"{API}/cart", cookies={COOKIE: session}).json()["count"] == 3


async def test_checkout_details_are_validated(client: TestClient) -> None:
    slug = await _seed_product()
    session = _register_and_login(client)
    _add_to_cart(client, session, slug)

    assert _checkout(client, session, contact_name="").status_code == 422
    assert _checkout(client, session, address_line="").status_code == 422
    # The failed attempts left no order behind; a valid one still succeeds.
    assert _checkout(client, session).status_code == 201
