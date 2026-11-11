"""Store operations: the admin product list, stock corrections, order filters, analytics.

Run through the real app and database. The order-filter tests also hold the SQL
search to the same answers as the domain's own ``OrderCriteria.matches``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import get_settings
from app.domains.orders.domain.criteria import OrderCriteria
from app.domains.orders.domain.enums import FulfillmentStatus, OrderPaymentStatus
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
PASSWORD = "Sup3rSecret!"
PRICE = Decimal("40000.00")


def _admin() -> dict[str, str]:
    return {COOKIE: session_strategy_from_settings().issue("1", role="admin")[0]}


async def _product(
    *, name: str | None = None, stock: int = 20, reserved: int = 0, active: bool = True,
    style: str = "Jersey",
) -> Product:
    tag = uuid4().hex[:8]
    product = Product(
        id=0, slug=f"ops-{tag}", name=name or f"Ops Jersey {tag}",
        category=Category(id=0, name="Ops", slug="ops"), price=PRICE, style=style,
        is_active=active, images=[ProductImage(url="/i.jpg", view="front")],
        variants=[
            ProductVariant(
                id=0, sku=f"O-{tag}-M", size="M",
                inventory=Inventory(quantity=stock, reserved=reserved),
            ),
            ProductVariant(id=0, sku=f"O-{tag}-L", size="L", inventory=Inventory(quantity=stock)),
        ],
    )
    engine = create_engine_from_url()
    try:
        async with SqlAlchemyUnitOfWork(build_sessionmaker(engine)) as uow:
            created = await uow.products.add(product)
            await uow.commit()
            return created
    finally:
        await engine.dispose()


def _shopper(client: TestClient, name: str = "Shopper") -> str:
    email = f"zoid-ops-{uuid4()}@example.com"
    client.post(f"{API}/auth/signup", json={"name": name, "email": email, "password": PASSWORD})
    return client.post(
        f"{API}/auth/login", json={"email": email, "password": PASSWORD}
    ).cookies.get(COOKIE)


def _place(client: TestClient, slug: str, *, qty: int = 1, delivery: dict | None = None,
           name: str = "Ada Zoid", session: str | None = None) -> dict:
    session = session or _shopper(client, name)
    client.post(
        f"{API}/cart/items", cookies={COOKIE: session},
        json={"product_slug": slug, "size": "M", "quantity": qty},
    )
    response = client.post(
        f"{API}/orders", cookies={COOKIE: session},
        json={"contact_name": name, "contact_email": "ada@example.com",
              "contact_phone": "+234 800 000 0000", "delivery": delivery or CHECKOUT_DELIVERY},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _settle(order_id: int, fulfillment: FulfillmentStatus | None = None) -> None:
    engine = create_engine_from_url()
    try:
        async with SqlAlchemyUnitOfWork(build_sessionmaker(engine)) as uow:
            order = await uow.orders.get_by_id(order_id)
            assert order is not None
            order.mark_paid(reference=f"PAY-{order_id:08d}")
            if fulfillment:
                order.set_fulfillment(fulfillment)
            await uow.orders.save(order)
            await uow.commit()
    finally:
        await engine.dispose()


async def _backdate(order_id: int, days: int) -> None:
    engine = create_engine_from_url()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE orders SET created_at = created_at - make_interval(days => :d) "
                     "WHERE id = :id"),
                {"d": days, "id": order_id},
            )
    finally:
        await engine.dispose()


# ── admin product list ──────────────────────────────────────────────────


async def test_the_admin_list_shows_hidden_products_the_storefront_does_not(
    client: TestClient,
) -> None:
    shown = await _product()
    hidden = await _product(active=False)

    admin = client.get(f"{API}/admin/products", cookies=_admin(), params={"page_size": 100}).json()
    storefront = client.get(f"{API}/products", params={"page_size": 100}).json()

    assert {p["slug"] for p in admin["items"]} == {shown.slug, hidden.slug}
    assert {p["slug"] for p in storefront["items"]} == {shown.slug}
    flags = {p["slug"]: p["is_active"] for p in admin["items"]}
    assert flags == {shown.slug: True, hidden.slug: False}


async def test_the_admin_list_filters_by_shelf_stock_and_search(client: TestClient) -> None:
    healthy = await _product(name="Healthy Milan", stock=20)
    low = await _product(name="Low Inter", stock=2)       # 4 units across two sizes
    empty = await _product(name="Empty City", stock=0)
    hidden = await _product(name="Hidden Lyon", active=False)

    def slugs(**params: str) -> set[str]:
        body = client.get(
            f"{API}/admin/products", cookies=_admin(), params={"page_size": 100, **params}
        ).json()
        return {p["slug"] for p in body["items"]}

    assert slugs(active="false") == {hidden.slug}
    assert slugs(active="true") == {healthy.slug, low.slug, empty.slug}
    assert slugs(stock="low_stock") == {low.slug}
    assert slugs(stock="out_of_stock") == {empty.slug}
    assert slugs(stock="in_stock") == {healthy.slug, hidden.slug}
    assert slugs(q="interr") == {low.slug}                       # the forgiving search
    assert slugs(sort="price_desc", q="healthy") == {healthy.slug}


async def test_archiving_hides_a_product_from_shoppers_and_unarchiving_restores_it(
    client: TestClient,
) -> None:
    product = await _product()
    url = f"{API}/admin/products/{product.id}"

    client.patch(url, cookies=_admin(), json={"is_active": False})
    assert client.get(f"{API}/products/{product.slug}").status_code == 404
    listed = client.get(f"{API}/admin/products", cookies=_admin(), params={"active": "false"})
    assert product.slug in {p["slug"] for p in listed.json()["items"]}

    client.patch(url, cookies=_admin(), json={"is_active": True})
    assert client.get(f"{API}/products/{product.slug}").status_code == 200


# ── stock corrections ───────────────────────────────────────────────────


def _adjust(client: TestClient, product_id: int, body: dict):
    return client.patch(f"{API}/admin/products/{product_id}/stock", cookies=_admin(), json=body)


async def test_stock_is_corrected_down_and_up_and_the_storefront_agrees(
    client: TestClient,
) -> None:
    product = await _product(stock=10)

    down = _adjust(client, product.id, {"size": "M", "delta": -4})
    assert down.status_code == 200, down.text
    assert down.json() == {"product_id": product.id, "size": "M", "change": -4,
                           "quantity": 6, "reserved": 0, "available": 6}
    assert _adjust(client, product.id, {"size": "m", "delta": 1}).json()["quantity"] == 7
    assert client.get(f"{API}/products/{product.slug}").json()["stock"]["M"] == 7


async def test_a_stock_take_sets_the_count(client: TestClient) -> None:
    product = await _product(stock=10)

    result = _adjust(client, product.id, {"size": "L", "set_to": 3}).json()

    assert (result["change"], result["quantity"]) == (-7, 3)
    assert _adjust(client, product.id, {"size": "L", "set_to": 3}).json()["change"] == 0


async def test_stock_cannot_be_taken_from_under_a_customers_order(client: TestClient) -> None:
    product = await _product(stock=10)
    _place(client, product.slug, qty=4)  # reserves 4 of size M

    refused = _adjust(client, product.id, {"size": "M", "set_to": 3})
    allowed = _adjust(client, product.id, {"size": "M", "set_to": 4})

    assert refused.status_code == 422 and "reserved" in refused.text
    assert allowed.status_code == 200
    assert (allowed.json()["reserved"], allowed.json()["available"]) == (4, 0)


async def test_stock_adjustments_are_validated(client: TestClient) -> None:
    product = await _product()

    assert _adjust(client, product.id, {"size": "M"}).status_code == 422                   # neither
    assert _adjust(client, product.id, {"size": "M", "delta": 1, "set_to": 5}).status_code == 422
    assert _adjust(client, product.id, {"size": "M", "delta": 0}).status_code == 422
    assert _adjust(client, product.id, {"size": "M", "set_to": -1}).status_code == 422
    assert _adjust(client, product.id, {"size": "M", "delta": -999}).status_code == 422
    assert _adjust(client, product.id, {"size": "XXL", "delta": 1}).status_code == 404
    assert _adjust(client, 999999, {"size": "M", "delta": 1}).status_code == 404


# ── order ledger filters ────────────────────────────────────────────────


def _ledger(client: TestClient, **params: str) -> dict:
    return client.get(
        f"{API}/admin/orders", cookies=_admin(), params={"page_size": 100, **params}
    ).json()


async def test_the_order_ledger_filters_and_counts_what_matched(client: TestClient) -> None:
    product = await _product()
    unpaid = _place(client, product.slug, name="Unpaid Una")
    processing = _place(client, product.slug, name="Pending Pat")
    shipped = _place(client, product.slug, name="Shipped Sam")
    pickup = _place(
        client, product.slug, name="Pickup Pia",
        delivery={"option": "pickup", "state": "Lagos State", "terminal": "Ojota"},
    )
    await _settle(processing["id"])
    await _settle(shipped["id"], FulfillmentStatus.IN_TRANSIT)
    await _settle(pickup["id"])

    def ids(**params: str) -> set[int]:
        return {o["id"] for o in _ledger(client, **params)["items"]}

    assert _ledger(client)["total"] == 4
    assert ids(payment_status="pending") == {unpaid["id"]}
    assert ids(payment_status="paid") == {processing["id"], shipped["id"], pickup["id"]}
    assert ids(fulfillment_status="in_transit") == {shipped["id"]}
    assert ids(delivery_option="pickup") == {pickup["id"]}
    assert ids(q="shipped sam") == {shipped["id"]}
    assert ids(q=unpaid["reference"].lower()) == {unpaid["id"]}
    assert ids(payment_status="paid", delivery_option="standard") == {
        processing["id"], shipped["id"]}
    narrowed = _ledger(client, payment_status="paid", page_size="1")
    assert (narrowed["total"], len(narrowed["items"]), narrowed["total_pages"]) == (3, 1, 3)


async def test_the_order_ledger_filters_by_date_in_store_time(client: TestClient) -> None:
    product = await _product()
    today = _place(client, product.slug)
    old = _place(client, product.slug)
    await _backdate(old["id"], 10)
    day = lambda offset: (datetime.now(UTC) + timedelta(days=offset)).date().isoformat()  # noqa: E731

    assert {o["id"] for o in _ledger(client, date_from=day(-1))["items"]} == {today["id"]}
    assert {o["id"] for o in _ledger(client, date_to=day(-5))["items"]} == {old["id"]}
    assert _ledger(client, date_from=day(-30), date_to=day(1))["total"] == 2
    assert _ledger(client, date_from=day(5))["total"] == 0


async def test_bad_ledger_filters_are_rejected(client: TestClient) -> None:
    for params in ({"payment_status": "maybe"}, {"fulfillment_status": "lost"},
                   {"delivery_option": "drone"}, {"date_from": "yesterday"}):
        response = client.get(f"{API}/admin/orders", cookies=_admin(), params=params)
        assert response.status_code == 422, params


async def test_sql_search_answers_the_same_as_the_domains_own_definition(
    client: TestClient,
) -> None:
    """The repository maps ``OrderCriteria`` to SQL; ``matches`` says what it should mean."""
    product = await _product()
    placed = [_place(client, product.slug, name=n) for n in ("Ann Ada", "Bob Bola", "Cy Chi")]
    await _settle(placed[0]["id"])
    await _settle(placed[1]["id"], FulfillmentStatus.DELIVERED)
    questions = [
        OrderCriteria(),
        OrderCriteria(payment_status=OrderPaymentStatus.PAID),
        OrderCriteria(payment_status=OrderPaymentStatus.PENDING),
        OrderCriteria(payment_status=OrderPaymentStatus.CANCELLED),
        OrderCriteria(fulfillment_status=FulfillmentStatus.DELIVERED),
        OrderCriteria(fulfillment_status=FulfillmentStatus.PROCESSING),
        OrderCriteria(delivery_option="standard"),
        OrderCriteria(delivery_option="pickup"),
        OrderCriteria(query="bola"),
        OrderCriteria(query="ZD-"),
        OrderCriteria(query="nobody"),
        OrderCriteria(created_before=datetime.now(UTC) + timedelta(days=1)),
        OrderCriteria(created_from=datetime.now(UTC) + timedelta(days=1)),
    ]

    engine = create_engine_from_url()
    try:
        async with SqlAlchemyUnitOfWork(build_sessionmaker(engine)) as uow:
            everything = await uow.orders.search(OrderCriteria())
            for criteria in questions:
                by_sql = {o.id for o in await uow.orders.search(criteria)}
                by_definition = {o.id for o in everything if criteria.matches(o)}
                assert by_sql == by_definition, criteria
                assert await uow.orders.count(criteria) == len(by_definition), criteria
    finally:
        await engine.dispose()


# ── analytics ───────────────────────────────────────────────────────────


async def test_analytics_report_real_money_not_hopes(client: TestClient) -> None:
    milan = await _product(name="Milan Home")
    inter = await _product(name="Inter Home")
    paid_two = _place(client, milan.slug, qty=2)                 # 80,000 + 2,500 delivery
    paid_one = _place(client, inter.slug, qty=1)                 # 40,000 + 2,500
    _place(client, inter.slug, qty=1)                            # unpaid: 42,500 outstanding
    await _settle(paid_two["id"], FulfillmentStatus.IN_TRANSIT)
    await _settle(paid_one["id"])
    today = datetime.now(UTC).date()

    response = client.get(
        f"{API}/admin/analytics", cookies=_admin(),
        params={"date_from": (today - timedelta(days=1)).isoformat(),
                "date_to": (today + timedelta(days=1)).isoformat()},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sales"]["revenue"] == "125000.00"                # 82,500 + 42,500
    assert (body["sales"]["orders"], body["sales"]["paid_orders"]) == (3, 2)
    assert body["sales"]["average_order_value"] == "62500.00"
    assert body["sales"]["units_sold"] == 3
    assert body["accounting"] == {
        "gross_sales": "120000.00", "customization_charges": "0.00",
        "delivery_charges": "5000.00", "total_collected": "125000.00",
        "outstanding": "42500.00",
    }
    assert body["operations"]["in_transit"] == 1 and body["operations"]["processing"] == 1
    assert body["operations"]["hand_delivery_orders"] == 3
    assert [(p["product_slug"], p["units_sold"], p["revenue"]) for p in body["top_products"]] == [
        (milan.slug, 2, "80000.00"), (inter.slug, 1, "40000.00")]
    assert body["period"]["days"] == 3 and len(body["daily"]) == 3
    assert sum(Decimal(point["revenue"]) for point in body["daily"]) == Decimal("125000.00")


async def test_analytics_compare_with_the_period_before(client: TestClient) -> None:
    product = await _product()
    now = _place(client, product.slug, qty=2)       # 82,500 this period
    before = _place(client, product.slug, qty=1)    # 42,500 the period before
    await _settle(now["id"])
    await _settle(before["id"])
    await _backdate(before["id"], 3)
    today = datetime.now(UTC).date()

    body = client.get(
        f"{API}/admin/analytics", cookies=_admin(),
        params={"date_from": (today - timedelta(days=1)).isoformat(),
                "date_to": (today + timedelta(days=1)).isoformat()},
    ).json()

    assert body["sales"]["revenue"] == "82500.00"
    assert body["sales"]["previous_revenue"] == "42500.00"
    assert body["sales"]["change_percent"] == 94  # (82,500 - 42,500) / 42,500


async def test_analytics_default_to_the_current_week(client: TestClient) -> None:
    body = client.get(f"{API}/admin/analytics", cookies=_admin()).json()

    first = datetime.fromisoformat(body["period"]["date_from"])
    assert (first.weekday(), body["period"]["days"]) == (0, 7)  # Monday, a full week
    assert body["sales"]["revenue"] == "0.00" and body["sales"]["change_percent"] is None


async def test_analytics_reject_impossible_periods(client: TestClient) -> None:
    def get(**params: str):
        return client.get(f"{API}/admin/analytics", cookies=_admin(), params=params)

    assert get(date_from="2026-11-08", date_to="2026-11-02").status_code == 422
    assert get(date_from="2024-01-01", date_to="2026-11-08").status_code == 422
    assert get(date_from="not-a-date").status_code == 422


async def test_only_admins_see_analytics(client: TestClient) -> None:
    session = _shopper(client)
    client.cookies.clear()
    assert client.get(f"{API}/admin/analytics").status_code == 401
    assert client.get(f"{API}/admin/analytics", cookies={COOKIE: session}).status_code == 403
    assert client.get(f"{API}/admin/products").status_code == 401
