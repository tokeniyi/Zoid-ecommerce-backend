"""Wishlist entities with explicit business rules.

A ``Wishlist`` belongs to exactly one authenticated user and holds a set of
saved products keyed by ``product_slug`` (matching the frontend, which stores a
list of slugs). ``WishlistItem`` snapshots a few display fields so the saved list
can be rendered without re-loading the whole catalog.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.shared.exceptions import ValidationError

# A new, not-yet-persisted entry is marked with this sentinel id.
NEW_ITEM_ID = 0


@dataclass
class WishlistItem:
    """A single saved product."""

    id: int
    product_slug: str
    product_name: str
    image: str = ""
    unit_price: Decimal = Decimal("0")
    currency: str = "NGN"

    def validate(self) -> None:
        if not self.product_slug:
            raise ValidationError("Wishlist item requires a product")
        if self.unit_price < Decimal("0"):
            raise ValidationError("Wishlist item price cannot be negative")


@dataclass
class Wishlist:
    """A user's saved-product list."""

    id: int
    user_id: int
    items: list[WishlistItem] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.items)

    def has(self, product_slug: str) -> bool:
        return any(item.product_slug == product_slug for item in self.items)

    def find_item(self, product_slug: str) -> WishlistItem | None:
        return next((item for item in self.items if item.product_slug == product_slug), None)

    def add_item(self, item: WishlistItem) -> bool:
        """Add a saved product; idempotent on slug. Returns True if it was new."""
        if self.has(item.product_slug):
            return False
        item.validate()
        self.items.append(item)
        return True

    def remove_item(self, product_slug: str) -> bool:
        """Remove a saved product. Returns True if something was removed."""
        item = self.find_item(product_slug)
        if item is None:
            return False
        self.items.remove(item)
        return True

    def validate(self) -> None:
        if self.user_id is None:
            raise ValidationError("Wishlist must belong to a user")
        for item in self.items:
            item.validate()
