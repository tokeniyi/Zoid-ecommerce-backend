"""Cart aggregate business rules — pure, no database or HTTP."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domains.cart.domain.entities import Cart, CartItem
from app.shared.exceptions import ValidationError


def _item(variant_id: int = 1, *, size: str = "M", qty: int = 1, price: str = "100.00") -> CartItem:
    return CartItem(
        id=0,
        variant_id=variant_id,
        product_slug="alpha",
        product_name="Alpha",
        size=size,
        quantity=qty,
        unit_price=Decimal(price),
    )


def test_guest_cart_starts_empty() -> None:
    cart = Cart(id=1, guest_token="tok")

    assert cart.count == 0
    assert cart.total == Decimal("0")
    cart.validate()  # guest token satisfies ownership


def test_add_item_appends_new_line() -> None:
    cart = Cart(id=1, guest_token="tok")
    cart.add_item(_item(variant_id=1, qty=2))

    assert cart.count == 2
    assert len(cart.items) == 1


def test_add_item_of_same_variant_increases_quantity() -> None:
    cart = Cart(id=1, guest_token="tok")
    cart.add_item(_item(variant_id=7, qty=1))
    cart.add_item(_item(variant_id=7, qty=3))

    assert len(cart.items) == 1
    assert cart.items[0].quantity == 4


def test_total_multiplies_unit_price_by_quantity() -> None:
    cart = Cart(id=1, guest_token="tok")
    cart.add_item(_item(variant_id=1, qty=2, price="150.00"))
    cart.add_item(_item(variant_id=2, qty=1, price="50.00"))

    assert cart.total == Decimal("350.00")


def test_set_quantity_updates_line() -> None:
    cart = Cart(id=1, user_id=5)
    cart.add_item(_item(variant_id=1))
    item_id = cart.items[0].id = 10

    cart.set_quantity(item_id, 6)

    assert cart.items[0].quantity == 6


def test_set_quantity_below_one_is_rejected() -> None:
    cart = Cart(id=1, user_id=5)
    cart.add_item(_item(variant_id=1))
    cart.items[0].id = 10

    with pytest.raises(ValidationError):
        cart.set_quantity(10, 0)


def test_remove_item_drops_line() -> None:
    cart = Cart(id=1, user_id=5)
    cart.add_item(_item(variant_id=1))
    cart.items[0].id = 10

    cart.remove_item(10)

    assert cart.items == []


def test_remove_unknown_item_is_noop() -> None:
    cart = Cart(id=1, user_id=5)
    cart.remove_item(999)  # does not raise

    assert cart.items == []


def test_cart_without_owner_is_invalid() -> None:
    with pytest.raises(ValidationError):
        Cart(id=1).validate()


def test_item_with_zero_quantity_is_invalid() -> None:
    with pytest.raises(ValidationError):
        _item(qty=0).validate()
