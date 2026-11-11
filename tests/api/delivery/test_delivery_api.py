"""Delivery quotes and priced checkout, through the real app and database.

The rate table is loaded with the shop's real service area (the same data the
``seed_delivery`` command installs), so these tests describe what a customer
actually experiences.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.cli.seed_delivery import build_rates, load_data, seed
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

pytestmark = pytest.mark.database

_settings = get_settings()
API = _settings.api_v1_prefix
COOKIE = _settings.cookie_name
PASSWORD = "Sup3rSecret!"
PRICE = Decimal("50000.00")

CONTACT = {
    "contact_name": "Ada Zoid",
    "contact_email": "ada@example.com",
    "contact_phone": "+234 800 000 0000",
}
HOME = {"option": "standard", "state": "Lagos State", "city": "Ikeja", "address": "5 Allen Avenue"}


@pytest.fixture
async def rates() -> None:
    await seed(build_rates(load_data()))


async def _seed_product(*, style: str = "Jersey", stock: int = 10) -> str:
    tag = uuid4().hex[:8]
    product = Product(
        id=0, slug=f"deliv-{tag}", name=f"Delivery Jersey {tag}",
        category=Category(id=0, name="Delivery", slug="delivery"), price=PRICE, style=style,
        images=[ProductImage(url="/i.jpg", view="front")],
        variants=[
            ProductVariant(id=0, sku=f"D-{tag}", size="M", inventory=Inventory(quantity=stock))
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


def _login(client: TestClient) -> str:
    email = f"zoid-deliv-{uuid4()}@example.com"
    client.post(
        f"{API}/auth/signup", json={"name": "Shopper", "email": email, "password": PASSWORD}
    )
    return client.post(
        f"{API}/auth/login", json={"email": email, "password": PASSWORD}
    ).cookies.get(COOKIE)


def _bag(client: TestClient, session: str, slug: str, *, qty: int = 1, text: str = "") -> None:
    response = client.post(
        f"{API}/cart/items", cookies={COOKIE: session},
        json={"product_slug": slug, "size": "M", "quantity": qty, "customization": text},
    )
    assert response.status_code == 200, response.text


def _order(client: TestClient, session: str, delivery: dict, **extra: object):
    return client.post(
        f"{API}/orders", cookies={COOKIE: session}, json={**CONTACT, "delivery": delivery, **extra}
    )


# ── POST /delivery/quote ────────────────────────────────────────────────


async def test_a_quote_needs_no_login_and_prices_a_served_address(
    client: TestClient, rates: None
) -> None:
    response = client.post(f"{API}/delivery/quote", json=HOME)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "option": "standard", "fee": "2500.00", "currency": "NGN", "is_student": False,
        "state": "Lagos State", "city": "Ikeja", "university": "", "terminal": "",
        "terminal_pending": False, "support_required": False, "message": "",
    }


async def test_express_costs_more_than_standard(client: TestClient, rates: None) -> None:
    express = client.post(f"{API}/delivery/quote", json={**HOME, "option": "express"}).json()
    assert express["fee"] == "4500.00"


async def test_a_campus_quote_reports_the_student_rate(client: TestClient, rates: None) -> None:
    body = client.post(
        f"{API}/delivery/quote",
        json={"option": "standard", "university": "Covenant University, Ota",
              "hostel_room": "Hall 3, Room 12"},
    ).json()

    assert (body["fee"], body["is_student"], body["state"]) == ("2500.00", True, "Ogun State")


async def test_an_unserved_place_is_an_answer_not_an_error(
    client: TestClient, rates: None
) -> None:
    response = client.post(
        f"{API}/delivery/quote",
        json={"option": "standard", "state": "Kano", "city": "Kano", "address": "1 Road"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["fee"] is None and body["support_required"] is True
    assert "terminal pickup" in body["message"]


async def test_pickup_is_free_and_unverified_terminals_are_flagged(
    client: TestClient, rates: None
) -> None:
    verified = client.post(
        f"{API}/delivery/quote",
        json={"option": "pickup", "state": "Lagos State",
              "terminal": "Ojota Terminal (7 Ikorodu Road, Ojota)"},
    ).json()
    unlisted = client.post(
        f"{API}/delivery/quote",
        json={"option": "pickup", "state": "Bauchi", "terminal": "Bauchi Park"},
    ).json()

    assert (verified["fee"], verified["terminal_pending"]) == ("0.00", False)
    assert (unlisted["fee"], unlisted["terminal_pending"]) == ("0.00", True)


async def test_incomplete_or_unknown_forms_are_rejected(client: TestClient, rates: None) -> None:
    assert client.post(f"{API}/delivery/quote", json={"option": "standard"}).status_code == 422
    assert client.post(f"{API}/delivery/quote", json={"option": "teleport"}).status_code == 422
    assert client.post(f"{API}/delivery/quote", json={}).status_code == 422


async def test_with_no_rates_set_every_place_needs_the_shop(client: TestClient) -> None:
    body = client.post(f"{API}/delivery/quote", json=HOME).json()
    assert body["fee"] is None and body["support_required"] is True


# ── checkout: the server prices everything ──────────────────────────────


async def test_checkout_adds_delivery_to_the_goods_and_records_where_it_goes(
    client: TestClient, rates: None
) -> None:
    slug = await _seed_product()
    session = _login(client)
    _bag(client, session, slug, qty=2)

    response = _order(client, session, HOME, notes="Call at the gate")

    assert response.status_code == 201, response.text
    order = response.json()
    assert (order["subtotal"], order["customization_total"]) == ("100000.00", "0.00")
    assert order["delivery"]["fee"] == "2500.00"
    assert order["total"] == "102500.00"
    assert order["delivery"] | {"fee": None} == {
        "option": "standard", "fee": None, "state": "Lagos State", "city": "Ikeja",
        "university": "", "hostel_room": "", "terminal": "", "terminal_pending": False,
        "note": "", "is_student": False,
    }
    assert (order["address_line"], order["city_state"]) == ("5 Allen Avenue", "Ikeja, Lagos State")


async def test_a_client_cannot_name_its_own_delivery_price(
    client: TestClient, rates: None
) -> None:
    slug = await _seed_product()
    session = _login(client)
    _bag(client, session, slug)

    order = _order(client, session, {**HOME, "fee": "0", "price": "1"}, total="1").json()

    assert order["delivery"]["fee"] == "2500.00"
    assert order["total"] == "52500.00"


async def test_a_jersey_with_a_name_and_number_costs_extra_per_unit(
    client: TestClient, rates: None
) -> None:
    slug = await _seed_product(style="Jersey")
    session = _login(client)
    _bag(client, session, slug, qty=2, text="Name: EDDY, #10")
    _bag(client, session, slug, qty=1)  # a plain one on the same order

    order = _order(client, session, HOME).json()

    assert order["customization_total"] == "4000.00"  # 2 units x 2,000
    assert order["total"] == "156500.00"  # 150,000 goods + 4,000 + 2,500 delivery
    by_text = {line["customization"]: line["customization_fee"] for line in order["items"]}
    assert by_text == {"Name: EDDY, #10": "2000.00", "": "0.00"}


async def test_personalising_something_that_is_not_a_jersey_is_not_charged(
    client: TestClient, rates: None
) -> None:
    slug = await _seed_product(style="Gym Kit")
    session = _login(client)
    _bag(client, session, slug, text="Name: ADA, #7")

    order = _order(client, session, HOME).json()

    assert order["customization_total"] == "0.00"
    assert order["total"] == "52500.00"
    assert order["items"][0]["customization"] == "Name: ADA, #7"  # still printed


async def test_pickup_orders_cost_nothing_extra_and_say_so(
    client: TestClient, rates: None
) -> None:
    slug = await _seed_product()
    session = _login(client)
    _bag(client, session, slug)

    order = _order(
        client, session,
        {"option": "pickup", "state": "Bauchi", "terminal": "Bauchi Motor Park"},
    ).json()

    assert order["delivery"]["fee"] == "0.00" and order["total"] == "50000.00"
    assert order["delivery"]["terminal_pending"] is True
    assert order["address_line"] == "GUO terminal pickup: Bauchi Motor Park"


async def test_a_campus_order_remembers_the_hostel(client: TestClient, rates: None) -> None:
    slug = await _seed_product()
    session = _login(client)
    _bag(client, session, slug)

    order = _order(
        client, session,
        {"option": "standard", "university": "Covenant University, Ota",
         "hostel_room": "Hall 3, Room 12"},
    ).json()

    assert order["delivery"]["is_student"] is True
    assert order["delivery"]["hostel_room"] == "Hall 3, Room 12"
    assert order["address_line"] == "Covenant University, Ota — Hall 3, Room 12"
    assert order["city_state"] == "Ogun State"


async def _reserved(slug: str) -> int:
    engine = create_engine_from_url()
    try:
        async with SqlAlchemyUnitOfWork(build_sessionmaker(engine)) as uow:
            product = await uow.products.get_by_slug(slug)
            assert product is not None
            return product.variants[0].inventory.reserved
    finally:
        await engine.dispose()


async def test_an_unserved_place_cannot_be_checked_out_and_reserves_nothing(
    client: TestClient, rates: None
) -> None:
    slug = await _seed_product()
    session = _login(client)
    _bag(client, session, slug)

    refused = _order(
        client, session,
        {"option": "standard", "state": "Kano", "city": "Kano", "address": "1 Road"},
    )

    assert refused.status_code == 422
    assert "not available" in refused.text
    assert await _reserved(slug) == 0
    # The bag is untouched, so the customer can switch to pickup and carry on.
    assert client.get(f"{API}/cart", cookies={COOKIE: session}).json()["count"] == 1


async def test_an_enquiry_is_not_a_checkout(client: TestClient, rates: None) -> None:
    slug = await _seed_product()
    session = _login(client)
    _bag(client, session, slug)

    refused = _order(client, session, {"option": "enquiry", "state": "Lagos State"})

    assert refused.status_code == 422
    assert await _reserved(slug) == 0


async def test_delivery_is_required_to_check_out(client: TestClient, rates: None) -> None:
    slug = await _seed_product()
    session = _login(client)
    _bag(client, session, slug)

    missing = client.post(f"{API}/orders", cookies={COOKIE: session}, json=CONTACT)
    incomplete = _order(client, session, {"option": "standard", "state": "Lagos State"})

    assert missing.status_code == 422
    assert incomplete.status_code == 422


async def test_the_amount_a_customer_pays_is_the_amount_on_the_order(
    client: TestClient, rates: None
) -> None:
    """Payment is initiated for the order's total, delivery and personalisation included."""
    slug = await _seed_product()
    session = _login(client)
    _bag(client, session, slug, text="Name: EDDY, #10")
    order = _order(client, session, HOME).json()

    fetched = client.get(f"{API}/orders/{order['id']}", cookies={COOKIE: session}).json()
    listed = client.get(f"{API}/orders", cookies={COOKIE: session}).json()

    assert fetched["total"] == order["total"] == "54500.00"  # 50,000 + 2,000 + 2,500
    assert listed[0]["total"] == "54500.00"
