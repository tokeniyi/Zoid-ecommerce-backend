"""Sales analytics for the shop's dashboard — pure functions over orders.

Nothing here reads a database or the clock: it is handed the orders of a period
(and of the period before it) and answers the questions the dashboard asks. That
keeps the *definitions* — what counts as revenue, what a "day" is — in one place
where they can be tested against known orders.

Definitions
-----------
* **Revenue** is money actually collected: the ``total`` of **paid** orders.
  An order nobody has paid for is not revenue, however eager the customer; the
  storefront's old in-browser numbers counted those, and this does not.
* **Outstanding** is the ``total`` of orders still awaiting payment.
* An order belongs to the calendar day (in the store's own timezone) on which it
  was *placed*.
* Cancelled orders are counted, but are neither revenue nor outstanding.
* Refunds are **not** netted off yet: ``gross_sales`` is before refunds.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from decimal import ROUND_HALF_UP, Decimal

from app.domains.orders.domain.entities import Order
from app.domains.orders.domain.enums import FulfillmentStatus, OrderPaymentStatus
from app.shared.exceptions import ValidationError

#: The widest range a report may span; a day-by-day trend beyond this is a
#: mistake, not a question.
MAX_DAYS = 366
TOP_PRODUCTS = 5
_ZERO = Decimal("0")


@dataclass(frozen=True)
class Period:
    """A run of whole calendar days in the store's timezone."""

    first_day: date
    last_day: date  # inclusive

    def __post_init__(self) -> None:
        if self.last_day < self.first_day:
            raise ValidationError("The end of the period is before its start.")
        if self.days > MAX_DAYS:
            raise ValidationError(f"A report can span at most {MAX_DAYS} days.")

    @property
    def days(self) -> int:
        return (self.last_day - self.first_day).days + 1

    def start(self, tz: tzinfo) -> datetime:
        return datetime.combine(self.first_day, time.min, tzinfo=tz).astimezone(UTC)

    def end(self, tz: tzinfo) -> datetime:
        """The first instant *after* the period (exclusive)."""
        return datetime.combine(self.last_day + timedelta(days=1), time.min, tzinfo=tz).astimezone(
            UTC
        )

    def previous(self) -> Period:
        """The period of equal length immediately before this one."""
        return Period(
            first_day=self.first_day - timedelta(days=self.days),
            last_day=self.first_day - timedelta(days=1),
        )

    @classmethod
    def week_of(cls, day: date) -> Period:
        """Monday to Sunday containing ``day``."""
        monday = day - timedelta(days=day.weekday())
        return cls(first_day=monday, last_day=monday + timedelta(days=6))


@dataclass(frozen=True)
class SalesSummary:
    revenue: Decimal
    orders: int
    paid_orders: int
    awaiting_payment_orders: int
    cancelled_orders: int
    units_sold: int
    average_order_value: Decimal
    previous_revenue: Decimal
    #: Whole-number change against the previous period; ``None`` when that had no revenue.
    change_percent: int | None


@dataclass(frozen=True)
class Accounting:
    gross_sales: Decimal
    customization_charges: Decimal
    delivery_charges: Decimal
    total_collected: Decimal
    outstanding: Decimal


@dataclass(frozen=True)
class Operations:
    processing: int
    in_transit: int
    delivered: int
    hand_delivery_orders: int
    pickup_orders: int
    pending_terminal_confirmations: int


@dataclass(frozen=True)
class TopProduct:
    product_slug: str
    product_name: str
    image: str
    units_sold: int
    revenue: Decimal


@dataclass(frozen=True)
class DailyPoint:
    day: date
    revenue: Decimal
    orders: int
    paid_orders: int
    units_sold: int


@dataclass(frozen=True)
class SalesReport:
    period: Period
    sales: SalesSummary
    accounting: Accounting
    operations: Operations
    top_products: list[TopProduct] = field(default_factory=list)
    daily: list[DailyPoint] = field(default_factory=list)


def _is_paid(order: Order) -> bool:
    return order.payment_status is OrderPaymentStatus.PAID


def _is_cancelled(order: Order) -> bool:
    return order.payment_status is OrderPaymentStatus.CANCELLED


def _units(order: Order) -> int:
    return sum(item.quantity for item in order.items)


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def build_report(
    orders: list[Order],
    previous_orders: list[Order],
    period: Period,
    tz: tzinfo,
) -> SalesReport:
    """Summarise ``orders`` (placed within ``period``) against ``previous_orders``."""
    paid = [order for order in orders if _is_paid(order)]
    live = [order for order in orders if not _is_cancelled(order)]

    revenue = sum((order.total for order in paid), _ZERO)
    previous_revenue = sum((o.total for o in previous_orders if _is_paid(o)), _ZERO)
    change = (
        int(((revenue - previous_revenue) / previous_revenue * 100).quantize(
            Decimal(1), rounding=ROUND_HALF_UP
        ))
        if previous_revenue > 0
        else None
    )

    sales = SalesSummary(
        revenue=_money(revenue),
        orders=len(live),
        paid_orders=len(paid),
        awaiting_payment_orders=sum(
            1 for o in orders if o.payment_status is OrderPaymentStatus.PENDING
        ),
        cancelled_orders=sum(1 for o in orders if _is_cancelled(o)),
        units_sold=sum(_units(order) for order in paid),
        average_order_value=_money(revenue / len(paid)) if paid else _ZERO,
        previous_revenue=_money(previous_revenue),
        change_percent=change,
    )
    accounting = Accounting(
        gross_sales=_money(sum((o.subtotal for o in paid), _ZERO)),
        customization_charges=_money(sum((o.customization_total for o in paid), _ZERO)),
        delivery_charges=_money(sum((o.delivery_fee for o in paid), _ZERO)),
        total_collected=_money(revenue),
        outstanding=_money(
            sum(
                (o.total for o in orders if o.payment_status is OrderPaymentStatus.PENDING),
                _ZERO,
            )
        ),
    )
    operations = Operations(
        processing=sum(1 for o in paid if o.fulfillment_status is FulfillmentStatus.PROCESSING),
        in_transit=sum(1 for o in paid if o.fulfillment_status is FulfillmentStatus.IN_TRANSIT),
        delivered=sum(1 for o in paid if o.fulfillment_status is FulfillmentStatus.DELIVERED),
        hand_delivery_orders=sum(1 for o in live if o.delivery_option in ("standard", "express")),
        pickup_orders=sum(1 for o in live if o.delivery_option == "pickup"),
        pending_terminal_confirmations=sum(
            1 for o in live if o.delivery_option == "pickup" and o.delivery_terminal_pending
        ),
    )
    return SalesReport(
        period=period,
        sales=sales,
        accounting=accounting,
        operations=operations,
        top_products=_top_products(paid),
        daily=_daily(orders, period, tz),
    )


def _top_products(paid: list[Order]) -> list[TopProduct]:
    totals: dict[str, TopProduct] = {}
    for order in paid:
        for item in order.items:
            seen = totals.get(item.product_slug)
            totals[item.product_slug] = TopProduct(
                product_slug=item.product_slug,
                product_name=item.product_name,
                image=item.image,
                units_sold=(seen.units_sold if seen else 0) + item.quantity,
                revenue=(seen.revenue if seen else _ZERO) + item.line_total,
            )
    ranked = sorted(totals.values(), key=lambda p: (-p.units_sold, -p.revenue, p.product_slug))
    return [
        TopProduct(p.product_slug, p.product_name, p.image, p.units_sold, _money(p.revenue))
        for p in ranked[:TOP_PRODUCTS]
    ]


def _daily(orders: list[Order], period: Period, tz: tzinfo) -> list[DailyPoint]:
    by_day: dict[date, list[Order]] = defaultdict(list)
    for order in orders:
        if order.created_at is not None:
            by_day[order.created_at.astimezone(tz).date()].append(order)
    points = []
    for offset in range(period.days):
        day = period.first_day + timedelta(days=offset)
        placed = by_day.get(day, [])
        paid = [o for o in placed if _is_paid(o)]
        points.append(
            DailyPoint(
                day=day,
                revenue=_money(sum((o.total for o in paid), _ZERO)),
                orders=sum(1 for o in placed if not _is_cancelled(o)),
                paid_orders=len(paid),
                units_sold=sum(_units(o) for o in paid),
            )
        )
    return points
