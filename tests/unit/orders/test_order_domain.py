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


# ── payment and fulfillment are two separate tracks ─────────────────────

from app.domains.orders.domain.enums import FulfillmentStatus, OrderPaymentStatus  # noqa: E402


def test_a_new_order_is_unpaid_and_not_yet_being_fulfilled() -> None:
    order = _order()
    assert order.payment_status is OrderPaymentStatus.PENDING
    assert order.fulfillment_status is FulfillmentStatus.PROCESSING
    assert order.payment_reference is None and order.paid_at is None


def test_paying_records_which_payment_settled_it_and_when() -> None:
    order = _order()

    assert order.mark_paid(reference="PAY-ABC123") is True

    assert order.payment_status is OrderPaymentStatus.PAID
    assert order.payment_reference == "PAY-ABC123"
    assert order.paid_at is not None


def test_a_repeated_payment_notice_changes_nothing_and_keeps_the_first_record() -> None:
    order = _order()
    order.mark_paid(reference="PAY-FIRST1")
    first_paid_at = order.paid_at

    assert order.mark_paid(reference="PAY-SECOND") is False

    assert (order.payment_reference, order.paid_at) == ("PAY-FIRST1", first_paid_at)


def test_a_cancelled_order_reports_cancelled_not_paid() -> None:
    assert _order(status=OrderStatus.CANCELLED).payment_status is OrderPaymentStatus.CANCELLED


def test_only_a_paid_order_can_be_fulfilled() -> None:
    order = _order()
    with pytest.raises(ConflictError, match="pending"):
        order.set_fulfillment(FulfillmentStatus.IN_TRANSIT)
    assert order.fulfillment_status is FulfillmentStatus.PROCESSING

    with pytest.raises(ConflictError, match="cancelled"):
        _order(status=OrderStatus.CANCELLED).set_fulfillment(FulfillmentStatus.DELIVERED)


def test_a_paid_order_moves_through_its_stages_and_can_be_corrected() -> None:
    order = _order()
    order.mark_paid(reference="PAY-ABC123")

    assert order.set_fulfillment(FulfillmentStatus.IN_TRANSIT) is True
    assert order.set_fulfillment(FulfillmentStatus.IN_TRANSIT) is False  # already there
    assert order.set_fulfillment(FulfillmentStatus.DELIVERED) is True
    assert order.set_fulfillment(FulfillmentStatus.PROCESSING) is True  # a tap on the wrong stage
    assert order.payment_status is OrderPaymentStatus.PAID  # never disturbed


def test_a_late_payment_notice_cannot_collide_with_a_parcel_in_transit() -> None:
    """Why fulfillment is its own field: the provider repeats a webhook after the
    shop has already delivered, and the order must simply say "already paid"."""
    order = _order()
    order.mark_paid(reference="PAY-ABC123")
    order.set_fulfillment(FulfillmentStatus.DELIVERED)

    assert order.mark_paid(reference="PAY-ABC123") is False  # no ConflictError

    assert order.fulfillment_status is FulfillmentStatus.DELIVERED


def test_the_shop_confirms_a_pickup_terminal() -> None:
    order = _order(
        delivery_option="pickup",
        delivery_terminal="Bauchi Park",
        delivery_terminal_pending=True,
    )

    order.confirm_terminal("  Bauchi Central Terminal ")

    assert order.delivery_terminal == "Bauchi Central Terminal"
    assert order.delivery_terminal_pending is False
    assert order.address_line == "GUO terminal pickup: Bauchi Central Terminal"


def test_only_pickup_orders_have_a_terminal_to_confirm() -> None:
    with pytest.raises(ConflictError, match="pickup"):
        _order(delivery_option="standard").confirm_terminal("Anywhere")
    with pytest.raises(ValidationError, match="required"):
        _order(delivery_option="pickup").confirm_terminal("   ")
