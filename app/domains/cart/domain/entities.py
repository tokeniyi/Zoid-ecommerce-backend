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

#: Longest personalisation text a line may carry. The storefront composes
#: "Name: <14 letters>, #<2 digits>" (or an official player's name), so this is
#: generous while still keeping the text printable and the column bounded.
MAX_CUSTOMIZATION_LENGTH = 100


def normalize_customization(text: str | None) -> str:
    """Trim and collapse whitespace; ``None``/blank mean "no personalisation"."""
    return " ".join((text or "").split())


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
    #: Free-text personalisation (e.g. "Name: EDDY, #10"); "" means none.
    customization: str = ""

    @property
    def line_total(self) -> Decimal:
        return self.unit_price * self.quantity

    @property
    def line_key(self) -> tuple[int, str]:
        """What makes two lines the same line: the variant *and* the text.

        Two shirts in one size are one line only when their personalisation
        matches; otherwise the shopper is buying two different things. The text
        is compared without regard to case ("eddy" and "EDDY" print the same).
        """
        return (self.variant_id, self.customization.casefold())

    def validate(self) -> None:
        if not self.product_slug:
            raise ValidationError("Cart item requires a product")
        if not self.size:
            raise ValidationError("Cart item requires a size")
        if self.quantity < 1:
            raise ValidationError("Cart item quantity must be at least 1")
        if self.unit_price < Decimal("0"):
            raise ValidationError("Cart item price cannot be negative")
        if len(self.customization) > MAX_CUSTOMIZATION_LENGTH:
            raise ValidationError(
                f"Personalisation must be at most {MAX_CUSTOMIZATION_LENGTH} characters"
            )


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

    def find_line(self, variant_id: int, customization: str = "") -> CartItem | None:
        """The line for this variant *with this personalisation*, if there is one."""
        key = (variant_id, customization.casefold())
        return next((item for item in self.items if item.line_key == key), None)

    def add_item(self, item: CartItem) -> None:
        """Add a line, or increase the quantity of the identical line already in the cart."""
        item.customization = normalize_customization(item.customization)
        item.validate()
        existing = self.find_line(item.variant_id, item.customization)
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
