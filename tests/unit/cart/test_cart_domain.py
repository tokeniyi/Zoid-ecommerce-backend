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


# ── personalisation: the text is part of the line's identity ────────────


def _custom(text: str, *, variant_id: int = 1, qty: int = 1) -> CartItem:
    item = _item(variant_id=variant_id, qty=qty)
    item.customization = text
    return item


def test_same_shirt_with_different_text_stays_two_lines() -> None:
    cart = Cart(id=1, guest_token="tok")
    cart.add_item(_custom("Name: EDDY, #10"))
    cart.add_item(_custom("Name: ADA, #7"))
    cart.add_item(_custom(""))

    assert len(cart.items) == 3
    assert cart.count == 3


def test_same_shirt_with_the_same_text_merges_into_one_line() -> None:
    cart = Cart(id=1, guest_token="tok")
    cart.add_item(_custom("Name: EDDY, #10", qty=1))
    cart.add_item(_custom("Name: EDDY, #10", qty=2))

    assert len(cart.items) == 1
    assert cart.items[0].quantity == 3


def test_text_is_trimmed_collapsed_and_compared_without_case() -> None:
    cart = Cart(id=1, guest_token="tok")
    cart.add_item(_custom("  Name:   EDDY,  #10 "))
    cart.add_item(_custom("name: eddy, #10"))

    assert len(cart.items) == 1
    assert cart.items[0].customization == "Name: EDDY, #10"  # first spelling kept


def test_blank_text_means_no_personalisation() -> None:
    cart = Cart(id=1, guest_token="tok")
    cart.add_item(_custom("   "))
    cart.add_item(_item(qty=2))

    assert len(cart.items) == 1
    assert cart.items[0].customization == ""
    assert cart.count == 3


def test_different_sizes_never_merge_whatever_the_text() -> None:
    cart = Cart(id=1, guest_token="tok")
    cart.add_item(_custom("Name: EDDY, #10", variant_id=1))
    cart.add_item(_custom("Name: EDDY, #10", variant_id=2))

    assert len(cart.items) == 2


def test_personalisation_has_a_length_limit() -> None:
    cart = Cart(id=1, guest_token="tok")
    cart.add_item(_custom("x" * 100))  # at the limit is fine
    with pytest.raises(ValidationError, match="at most 100"):
        cart.add_item(_custom("x" * 101, variant_id=2))


def test_find_line_looks_up_by_variant_and_text() -> None:
    cart = Cart(id=1, guest_token="tok")
    cart.add_item(_custom("A"))
    cart.add_item(_custom(""))

    assert cart.find_line(1, "a") is cart.items[0]
    assert cart.find_line(1, "") is cart.items[1]
    assert cart.find_line(1, "B") is None
