"""Wishlist aggregate business rules — pure, no database or HTTP."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domains.wishlist.domain.entities import Wishlist, WishlistItem
from app.shared.exceptions import ValidationError


def _item(slug: str = "alpha", *, price: str = "100.00") -> WishlistItem:
    return WishlistItem(
        id=0,
        product_slug=slug,
        product_name=f"Product {slug}",
        unit_price=Decimal(price),
    )


def test_new_wishlist_is_empty() -> None:
    wishlist = Wishlist(id=1, user_id=7, items=[])

    assert wishlist.count == 0
    wishlist.validate()


def test_add_item_appends() -> None:
    wishlist = Wishlist(id=1, user_id=7, items=[])

    assert wishlist.add_item(_item("alpha")) is True
    assert wishlist.count == 1
    assert wishlist.has("alpha")


def test_add_item_is_idempotent_on_slug() -> None:
    wishlist = Wishlist(id=1, user_id=7, items=[])
    wishlist.add_item(_item("alpha"))

    assert wishlist.add_item(_item("alpha")) is False
    assert wishlist.count == 1


def test_remove_item_reports_whether_it_removed() -> None:
    wishlist = Wishlist(id=1, user_id=7, items=[])
    wishlist.add_item(_item("alpha"))

    assert wishlist.remove_item("alpha") is True
    assert wishlist.remove_item("alpha") is False
    assert wishlist.count == 0


def test_find_item_returns_match_or_none() -> None:
    wishlist = Wishlist(id=1, user_id=7, items=[])
    wishlist.add_item(_item("beta"))

    assert wishlist.find_item("beta") is not None
    assert wishlist.find_item("missing") is None


def test_wishlist_without_user_is_invalid() -> None:
    with pytest.raises(ValidationError):
        Wishlist(id=1, user_id=None, items=[]).validate()  # type: ignore[arg-type]


def test_item_without_product_is_invalid() -> None:
    with pytest.raises(ValidationError):
        WishlistItem(id=0, product_slug="", product_name="X").validate()
