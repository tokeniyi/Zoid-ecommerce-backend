"""Sales analytics: what counts as revenue, and which day an order belongs to.

Built from orders whose right answers can be worked out by hand.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.domains.admin.application.analytics import Period, build_report
from app.domains.orders.domain.criteria import OrderCriteria
from app.domains.orders.domain.entities import Order, OrderItem
from app.domains.orders.domain.enums import FulfillmentStatus, OrderPaymentStatus, OrderStatus
from app.shared.exceptions import ValidationError

LAGOS = timezone(timedelta(hours=1))  # the store's clock: UTC+1, no daylight saving
WEEK = Period(first_day=date(2026, 11, 2), last_day=date(2026, 11, 8))  # Mon..Sun


def _order(
    *,
    when: datetime,
    price: str = "50000",
    qty: int = 1,
    slug: str = "alpha",
    fee: str = "2500",
    custom: str = "0",
    paid: bool = False,
    cancelled: bool = False,
    fulfillment: FulfillmentStatus = FulfillmentStatus.PROCESSING,
    option: str = "standard",
    terminal_pending: bool = False,
    name: str = "Ada Zoid",
) -> Order:
    order = Order(
        id=0, reference=f"ZD-{abs(hash((when, slug, qty, price))) % 10**8:08d}", user_id=1,
        contact_name=name, contact_email="ada@example.com", contact_phone="+234 800 000 0000",
        address_line="x", items=[
            OrderItem(
                id=0, variant_id=1, product_slug=slug, product_name=slug.title(), size="M",
                quantity=qty, unit_price=Decimal(price), image=f"/{slug}.jpg",
                customization_fee=Decimal(custom),
            )
        ],
        delivery_fee=Decimal(fee), delivery_option=option,
        delivery_terminal_pending=terminal_pending, created_at=when,
    )
    if paid:
        order.mark_paid(reference="PAY-X", at=when)
        order.fulfillment_status = fulfillment
    if cancelled:
        order.status = OrderStatus.CANCELLED
    return order


def at(day: int, hour: int = 12, *, tz: timezone = LAGOS) -> datetime:
    return datetime(2026, 11, day, hour, 0, tzinfo=tz).astimezone(UTC)


# ── periods ─────────────────────────────────────────────────────────────


def test_a_week_runs_monday_to_sunday() -> None:
    for day in (date(2026, 11, 2), date(2026, 11, 5), date(2026, 11, 8)):
        assert Period.week_of(day) == WEEK


def test_the_previous_period_is_the_same_length_just_before() -> None:
    assert WEEK.previous() == Period(date(2026, 10, 26), date(2026, 11, 1))
    one_day = Period(date(2026, 11, 5), date(2026, 11, 5))
    assert one_day.previous() == Period(date(2026, 11, 4), date(2026, 11, 4))


def test_period_bounds_are_in_the_stores_timezone() -> None:
    # Lagos midnight is 23:00 UTC the evening before.
    assert WEEK.start(LAGOS) == datetime(2026, 11, 1, 23, 0, tzinfo=UTC)
    assert WEEK.end(LAGOS) == datetime(2026, 11, 8, 23, 0, tzinfo=UTC)


def test_a_backwards_or_enormous_period_is_refused() -> None:
    with pytest.raises(ValidationError, match="before"):
        Period(date(2026, 11, 8), date(2026, 11, 2))
    with pytest.raises(ValidationError, match="at most"):
        Period(date(2025, 1, 1), date(2026, 11, 8))


# ── revenue is money collected ──────────────────────────────────────────


def test_only_paid_orders_are_revenue() -> None:
    orders = [
        _order(when=at(3), paid=True),                  # 50,000 + 2,500 = 52,500
        _order(when=at(4), price="30000", paid=True),   # 30,000 + 2,500 = 32,500
        _order(when=at(5)),                             # unpaid: outstanding, not revenue
        _order(when=at(6), cancelled=True),             # cancelled: neither
    ]

    report = build_report(orders, [], WEEK, LAGOS)

    assert report.sales.revenue == Decimal("85000.00")
    assert report.accounting.total_collected == Decimal("85000.00")
    assert report.accounting.outstanding == Decimal("52500.00")
    assert (report.sales.orders, report.sales.paid_orders) == (3, 2)  # cancelled not "live"
    assert report.sales.awaiting_payment_orders == 1
    assert report.sales.cancelled_orders == 1
    assert report.sales.average_order_value == Decimal("42500.00")


def test_accounting_separates_goods_personalisation_and_delivery() -> None:
    orders = [_order(when=at(3), price="50000", qty=2, custom="2000", fee="4500", paid=True)]

    accounting = build_report(orders, [], WEEK, LAGOS).accounting

    assert accounting.gross_sales == Decimal("100000.00")       # the goods alone
    assert accounting.customization_charges == Decimal("4000.00")  # 2 units x 2,000
    assert accounting.delivery_charges == Decimal("4500.00")
    assert accounting.total_collected == Decimal("108500.00")   # the three together


def test_change_against_the_previous_period() -> None:
    now = [_order(when=at(3), price="150000", fee="0", paid=True)]
    before = [_order(when=at(3) - timedelta(days=7), price="100000", fee="0", paid=True)]

    assert build_report(now, before, WEEK, LAGOS).sales.change_percent == 50
    assert build_report(before, now, WEEK, LAGOS).sales.change_percent == -33  # 100 vs 150
    # With nothing to compare against there is no percentage, not "infinite".
    assert build_report(now, [], WEEK, LAGOS).sales.change_percent is None
    assert build_report(now, [], WEEK, LAGOS).sales.previous_revenue == Decimal("0.00")


def test_an_empty_period_is_all_zeros_not_an_error() -> None:
    report = build_report([], [], WEEK, LAGOS)

    assert report.sales.revenue == Decimal("0.00")
    assert report.sales.average_order_value == Decimal("0.00")
    assert report.top_products == []
    assert [point.revenue for point in report.daily] == [Decimal("0.00")] * 7


# ── operations ──────────────────────────────────────────────────────────


def test_operations_count_the_shops_workload() -> None:
    orders = [
        _order(when=at(3), paid=True),
        _order(when=at(3), paid=True, fulfillment=FulfillmentStatus.IN_TRANSIT),
        _order(when=at(4), paid=True, fulfillment=FulfillmentStatus.DELIVERED, option="express"),
        _order(when=at(4), paid=True, option="pickup", terminal_pending=True),
        _order(when=at(5), option="pickup"),            # unpaid pickup still needs a terminal
        _order(when=at(6), cancelled=True, option="pickup", terminal_pending=True),
    ]

    ops = build_report(orders, [], WEEK, LAGOS).operations

    assert (ops.processing, ops.in_transit, ops.delivered) == (2, 1, 1)  # paid orders only
    assert ops.hand_delivery_orders == 3   # standard x2 + express (cancelled excluded)
    assert ops.pickup_orders == 2
    assert ops.pending_terminal_confirmations == 1  # the cancelled one does not count


# ── best sellers ────────────────────────────────────────────────────────


def test_top_products_rank_by_units_then_revenue_from_paid_orders_only() -> None:
    orders = [
        _order(when=at(3), slug="milan", qty=3, price="50000", paid=True),
        _order(when=at(4), slug="inter", qty=2, price="60000", paid=True),
        _order(when=at(4), slug="city", qty=2, price="70000", paid=True),  # ties inter on units
        _order(when=at(5), slug="ghost", qty=9, price="1000"),             # unpaid: ignored
    ]

    top = build_report(orders, [], WEEK, LAGOS).top_products

    ranked = [(p.product_slug, p.units_sold) for p in top]
    assert ranked == [("milan", 3), ("city", 2), ("inter", 2)]
    assert top[0].revenue == Decimal("150000.00")
    assert top[0].image == "/milan.jpg"


def test_only_the_top_five_are_listed() -> None:
    orders = [_order(when=at(3), slug=f"p{i}", qty=i, paid=True) for i in range(1, 9)]
    top = build_report(orders, [], WEEK, LAGOS).top_products
    assert [p.product_slug for p in top] == ["p8", "p7", "p6", "p5", "p4"]


# ── the day-by-day trend ────────────────────────────────────────────────


def test_every_day_of_the_period_has_a_point_even_when_quiet() -> None:
    daily = build_report([_order(when=at(4), paid=True)], [], WEEK, LAGOS).daily

    assert [point.day for point in daily] == [date(2026, 11, d) for d in range(2, 9)]
    assert [point.revenue for point in daily][2] == Decimal("52500.00")  # Wednesday 4th
    assert sum(point.orders for point in daily) == 1


def test_an_order_belongs_to_the_day_in_the_stores_timezone_not_utc() -> None:
    # 23:30 UTC on the 3rd is 00:30 on the 4th in Lagos.
    late = _order(when=datetime(2026, 11, 3, 23, 30, tzinfo=UTC), paid=True)
    # 22:30 UTC on the 3rd is 23:30 on the 3rd in Lagos.
    earlier = _order(when=datetime(2026, 11, 3, 22, 30, tzinfo=UTC), price="10000", paid=True)

    daily = {p.day: p for p in build_report([late, earlier], [], WEEK, LAGOS).daily}

    assert daily[date(2026, 11, 4)].revenue == Decimal("52500.00")
    assert daily[date(2026, 11, 3)].revenue == Decimal("12500.00")


def test_a_days_units_and_orders() -> None:
    orders = [
        _order(when=at(3, 9), qty=2, paid=True),
        _order(when=at(3, 15), qty=1, paid=True),
        _order(when=at(3, 16), qty=5),                    # unpaid: an order, no units sold
    ]

    point = next(p for p in build_report(orders, [], WEEK, LAGOS).daily if p.day.day == 3)

    assert (point.orders, point.paid_orders, point.units_sold) == (3, 2, 3)


# ── OrderCriteria.matches: the definition storage has to agree with ─────


@pytest.mark.parametrize(
    ("criteria", "expected"),
    [
        (OrderCriteria(), True),
        (OrderCriteria(payment_status=OrderPaymentStatus.PAID), True),
        (OrderCriteria(payment_status=OrderPaymentStatus.PENDING), False),
        (OrderCriteria(fulfillment_status=FulfillmentStatus.PROCESSING), True),
        (OrderCriteria(fulfillment_status=FulfillmentStatus.DELIVERED), False),
        (OrderCriteria(delivery_option="standard"), True),
        (OrderCriteria(delivery_option="pickup"), False),
        (OrderCriteria(query="ada"), True),
        (OrderCriteria(query="  ZOID "), True),
        (OrderCriteria(query="+234 800"), True),
        (OrderCriteria(query="nobody"), False),
        (OrderCriteria(created_from=at(3), created_before=at(4)), True),
        (OrderCriteria(created_from=at(4)), False),
        (OrderCriteria(created_before=at(3)), False),  # exclusive upper bound
    ],
)
def test_criteria_matching(criteria: OrderCriteria, expected: bool) -> None:
    order = _order(when=at(3), paid=True)
    assert criteria.matches(order) is expected
