"""Payment status, fulfillment status and what the shop can do about each."""

from __future__ import annotations

import secrets
from decimal import Decimal
from uuid import uuid4

import pytest
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
from app.security.authentication.session import session_strategy_from_settings
from tests.support.delivery import CHECKOUT_DELIVERY

pytestmark = [pytest.mark.database, pytest.mark.usefixtures("basic_delivery_rates")]

_settings = get_settings()
API = _settings.api_v1_prefix
COOKIE = _settings.cookie_name
PASSWORD = secrets.token_urlsafe(16)  # fresh every run: no credential in the source
CONTACT = {
    "contact_name": "Ada Zoid",
    "contact_email": "ada@example.com",
    "contact_phone": "+234 800 000 0000",
}


async def _slug() -> str:
    tag = uuid4().hex[:8]
    product = Product(
        id=0, slug=f"life-{tag}", name=f"Lifecycle Jersey {tag}",
        category=Category(id=0, name="Life", slug="life"), price=Decimal("30000.00"),
        images=[ProductImage(url="/i.jpg", view="front")],
        variants=[
            ProductVariant(id=0, sku=f"L-{tag}", size="M", inventory=Inventory(quantity=50))
        ],
    )
    engine = create_engine_from_url()
    try:
        async with SqlAlchemyUnitOfWork(build_sessionmaker(engine)) as uow:
            await uow.products.add(product)
            await uow.commit()
    finally:
        await engine.dispose()
    return product.slug


def _shopper(client: TestClient) -> str:
    email = f"zoid-life-{uuid4()}@example.com"
    client.post(
        f"{API}/auth/signup", json={"name": "Shopper", "email": email, "password": PASSWORD}
    )
    return client.post(
        f"{API}/auth/login", json={"email": email, "password": PASSWORD}
    ).cookies.get(COOKIE)


def _admin() -> str:
    return session_strategy_from_settings().issue("1", role="admin")[0]


def _place(client: TestClient, session: str, slug: str, delivery: dict | None = None) -> dict:
    client.post(
        f"{API}/cart/items", cookies={COOKIE: session},
        json={"product_slug": slug, "size": "M", "quantity": 1},
    )
    response = client.post(
        f"{API}/orders", cookies={COOKIE: session},
        json={**CONTACT, "delivery": delivery or CHECKOUT_DELIVERY},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _settle(order_id: int, reference: str = "PAY-LIFE0001") -> None:
    """Confirm a payment the way the payments domain does."""
    engine = create_engine_from_url()
    try:
        async with SqlAlchemyUnitOfWork(build_sessionmaker(engine)) as uow:
            order = await uow.orders.get_by_id(order_id)
            assert order is not None
            order.mark_paid(reference=reference)
            await uow.orders.save(order)
            await uow.commit()
    finally:
        await engine.dispose()


def _fulfil(client: TestClient, order_id: int, body: dict, *, cookie: str | None = None):
    return client.patch(
        f"{API}/admin/orders/{order_id}/fulfillment",
        cookies={COOKIE: cookie or _admin()}, json=body,
    )


async def test_a_new_order_reports_unpaid_and_processing(client: TestClient) -> None:
    order = _place(client, _shopper(client), await _slug())

    assert order["payment_status"] == "pending"
    assert order["fulfillment_status"] == "processing"
    assert order["payment_reference"] is None and order["paid_at"] is None


async def test_the_customer_sees_the_payment_that_settled_the_order(
    client: TestClient,
) -> None:
    session = _shopper(client)
    order = _place(client, session, await _slug())
    await _settle(order["id"])

    seen = client.get(f"{API}/orders/{order['id']}", cookies={COOKIE: session}).json()

    assert seen["payment_status"] == "paid"
    assert seen["payment_reference"] == "PAY-LIFE0001"
    assert seen["paid_at"] is not None


async def test_the_shop_cannot_ship_what_has_not_been_paid_for(client: TestClient) -> None:
    order = _place(client, _shopper(client), await _slug())

    response = _fulfil(client, order["id"], {"status": "in_transit"})

    assert response.status_code == 409
    assert "pending" in response.text


async def test_the_shop_moves_a_paid_order_along_and_the_customer_sees_it(
    client: TestClient,
) -> None:
    session = _shopper(client)
    order = _place(client, session, await _slug())
    await _settle(order["id"])

    in_transit = _fulfil(client, order["id"], {"status": "in_transit"})
    assert in_transit.status_code == 200, in_transit.text
    assert in_transit.json()["fulfillment_status"] == "in_transit"
    assert in_transit.json()["payment_status"] == "paid"  # untouched

    seen = client.get(f"{API}/orders/{order['id']}", cookies={COOKIE: session}).json()
    assert seen["fulfillment_status"] == "in_transit"

    assert _fulfil(client, order["id"], {"status": "delivered"}).json()[
        "fulfillment_status"
    ] == "delivered"
    # A wrong tap can be put right.
    assert _fulfil(client, order["id"], {"status": "in_transit"}).status_code == 200


async def test_the_shop_confirms_the_terminal_of_a_pickup_order(client: TestClient) -> None:
    session = _shopper(client)
    order = _place(
        client, session, await _slug(),
        {"option": "pickup", "state": "Bauchi", "terminal": "Bauchi Park"},
    )
    assert order["delivery"]["terminal_pending"] is True
    await _settle(order["id"])

    confirmed = _fulfil(client, order["id"], {"terminal": "Bauchi Central Terminal"})

    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["delivery"]["terminal"] == "Bauchi Central Terminal"
    assert body["delivery"]["terminal_pending"] is False
    assert body["address_line"] == "GUO terminal pickup: Bauchi Central Terminal"
    assert body["fulfillment_status"] == "processing"  # only the terminal was sent
    seen = client.get(f"{API}/orders/{order['id']}", cookies={COOKIE: session}).json()
    assert seen["delivery"]["terminal"] == "Bauchi Central Terminal"


async def test_a_home_delivery_order_has_no_terminal_to_confirm(client: TestClient) -> None:
    order = _place(client, _shopper(client), await _slug())
    await _settle(order["id"])

    assert _fulfil(client, order["id"], {"terminal": "Somewhere"}).status_code == 409


async def test_a_refused_part_means_nothing_is_saved(client: TestClient) -> None:
    """Status and terminal together: the terminal is refused, so the status is not applied."""
    order = _place(client, _shopper(client), await _slug())
    await _settle(order["id"])

    refused = _fulfil(client, order["id"], {"status": "delivered", "terminal": "Nope"})

    assert refused.status_code == 409
    listed = client.get(
        f"{API}/admin/orders", cookies={COOKIE: _admin()}, params={"page_size": 100}
    ).json()["items"]
    assert next(o for o in listed if o["id"] == order["id"])["fulfillment_status"] == "processing"


async def test_an_update_must_say_something_and_name_a_real_order(client: TestClient) -> None:
    order = _place(client, _shopper(client), await _slug())
    await _settle(order["id"])

    assert _fulfil(client, order["id"], {}).status_code == 422
    assert _fulfil(client, order["id"], {"status": "teleported"}).status_code == 422
    assert _fulfil(client, 999999, {"status": "delivered"}).status_code == 404


async def test_only_an_admin_can_update_fulfillment(client: TestClient) -> None:
    session = _shopper(client)
    order = _place(client, session, await _slug())
    await _settle(order["id"])

    url = f"{API}/admin/orders/{order['id']}/fulfillment"
    client.cookies.clear()  # the shopper's login lives in the client's jar; be anonymous
    assert client.patch(url, json={"status": "delivered"}).status_code == 401
    assert client.patch(
        url, cookies={COOKIE: session}, json={"status": "delivered"}
    ).status_code == 403


async def test_the_customers_order_list_carries_the_lines_and_statuses(
    client: TestClient,
) -> None:
    session = _shopper(client)
    slug = await _slug()
    first = _place(client, session, slug)
    second = _place(client, session, slug)
    await _settle(first["id"], "PAY-FIRST001")

    listed = client.get(f"{API}/orders", cookies={COOKIE: session}).json()

    assert [o["id"] for o in listed] == [second["id"], first["id"]]  # newest first
    assert all(o["items"] and o["items"][0]["product_slug"] == slug for o in listed)
    by_id = {o["id"]: o for o in listed}
    assert by_id[first["id"]]["payment_status"] == "paid"
    assert by_id[second["id"]]["payment_status"] == "pending"
    assert by_id[first["id"]]["payment_reference"] == "PAY-FIRST001"
