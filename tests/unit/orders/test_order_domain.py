"""Unit tests for the orders domain model (no framework, no database)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domains.orders.domain.entities import Order, OrderItem
from app.domains.orders.domain.enums import OrderStatus
from app.shared.exceptions import ConflictError, ValidationError


def _item(*, quantity: int = 1, price: str = "58500.00", size: str = "M") -> OrderItem:
    return OrderItem(
        id=0,
        variant_id=11,
        product_slug="alpha",
        product_name="Alpha Jersey",
        size=size,
        quantity=quantity,
        unit_price=Decimal(price),
    )


def _order(**overrides: object) -> Order:
    kwargs: dict = {
        "id": 0,
        "reference": "ZD-ABC12345",
        "user_id": 7,
        "contact_name": "Ada Zoid",
        "contact_email": "ada@example.com",
        "address_line": "12 Concrete Road",
        "items": [_item()],
    }
    kwargs.update(overrides)
    return Order(**kwargs)  # type: ignore[arg-type]


def test_order_starts_pending_payment() -> None:
    order = _order()

    assert order.status is OrderStatus.PENDING_PAYMENT
    assert order.is_pending_payment is True


def test_line_total_and_order_totals() -> None:
    order = _order(items=[_item(quantity=2), _item(quantity=1, price="1000.00", size="L")])

    assert order.items[0].line_total == Decimal("117000.00")
    assert order.subtotal == Decimal("118000.00")
    # Shipping is not priced yet: the amount due equals the goods subtotal.
    assert order.total == order.subtotal
    assert order.item_count == 3


@pytest.mark.parametrize(
    "overrides",
    [
        {"reference": ""},
        {"user_id": None},
        {"contact_name": ""},
        {"contact_email": ""},
        {"address_line": ""},
        {"items": []},
    ],
)
def test_order_validation_rejects_incomplete_orders(overrides: dict) -> None:
    order = _order(**overrides)

    with pytest.raises(ValidationError):
        order.validate()


def test_valid_order_passes_validation() -> None:
    _order().validate()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"product_slug": ""},
        {"size": ""},
        {"quantity": 0},
        {"unit_price": Decimal("-1.00")},
    ],
)
def test_order_item_validation(kwargs: dict) -> None:
    item = _item()
    for key, value in kwargs.items():
        setattr(item, key, value)

    with pytest.raises(ValidationError):
        item.validate()


def test_find_item_by_id() -> None:
    item = _order(items=[_item()]).items[0]
    item.id = 42
    order = _order(items=[item])

    assert order.find_item(42) is item
    assert order.find_item(999) is None


# --- the payment confirmation, from the order's side --------------------------


def test_a_confirmed_payment_moves_the_order_once() -> None:
    order = _order()

    assert order.mark_paid() is True
    assert order.status is OrderStatus.PAID


def test_hearing_the_same_news_twice_changes_nothing() -> None:
    """A webhook arriving after a verification must not re-pay anything."""
    order = _order()
    order.mark_paid()

    assert order.mark_paid() is False
    assert order.status is OrderStatus.PAID


@pytest.mark.parametrize(
    "status",
    [
        OrderStatus.PROCESSING,
        OrderStatus.SHIPPED,
        OrderStatus.DELIVERED,
        OrderStatus.CANCELLED,
    ],
)
def test_an_order_beyond_payment_is_not_re_paid(status: OrderStatus) -> None:
    """Payment is settled before an order ships; a late 'paid' is a contradiction."""
    order = _order(status=status)

    with pytest.raises(ConflictError):
        order.mark_paid()
