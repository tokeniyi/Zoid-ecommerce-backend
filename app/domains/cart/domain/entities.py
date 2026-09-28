"""Cart entities with explicit business rules.

A ``Cart`` is either a *guest* cart (identified by an opaque ``guest_token``
handed to the browser as a cookie) or an *authenticated* cart (attached to a
``user_id``). ``CartItem`` snapshots the product/variant details at add-time so
the cart renders without reaching back into the products aggregate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.shared.exceptions import ValidationError

# A new, not-yet-persisted line is marked with this sentinel id.
NEW_ITEM_ID = 0


@dataclass
class CartItem:
    """A single line in the bag, keyed by product variant."""

    id: int
    variant_id: int
    product_slug: str
    product_name: str
    size: str
    quantity: int
    unit_price: Decimal
    image: str = ""
    currency: str = "NGN"

    @property
    def line_total(self) -> Decimal:
        return self.unit_price * self.quantity

    def validate(self) -> None:
        if not self.product_slug:
            raise ValidationError("Cart item requires a product")
        if not self.size:
            raise ValidationError("Cart item requires a size")
        if self.quantity < 1:
            raise ValidationError("Cart item quantity must be at least 1")
        if self.unit_price < Decimal("0"):
            raise ValidationError("Cart item price cannot be negative")


@dataclass
class Cart:
    """A guest or authenticated cart aggregate."""

    id: int
    guest_token: str | None = None
    user_id: int | None = None
    currency: str = "NGN"
    items: list[CartItem] = field(default_factory=list)

    @property
    def count(self) -> int:
        return sum(item.quantity for item in self.items)

    @property
    def total(self) -> Decimal:
        return sum((item.line_total for item in self.items), Decimal("0"))

    def find_item(self, item_id: int) -> CartItem | None:
        return next((item for item in self.items if item.id == item_id), None)

    def find_item_by_variant(self, variant_id: int) -> CartItem | None:
        return next((item for item in self.items if item.variant_id == variant_id), None)

    def add_item(self, item: CartItem) -> None:
        """Add a line, or increase the quantity if the variant is already in the cart."""
        item.validate()
        existing = self.find_item_by_variant(item.variant_id)
        if existing is not None:
            existing.quantity += item.quantity
            existing.validate()
        else:
            self.items.append(item)

    def set_quantity(self, item_id: int, quantity: int) -> None:
        item = self.find_item(item_id)
        if item is None:
            raise ValidationError("Cart item not found")
        item.quantity = quantity
        item.validate()

    def remove_item(self, item_id: int) -> None:
        item = self.find_item(item_id)
        if item is not None:
            self.items.remove(item)

    def validate(self) -> None:
        if self.guest_token is None and self.user_id is None:
            raise ValidationError("Cart must belong to a guest token or a user")
        for item in self.items:
            item.validate()
