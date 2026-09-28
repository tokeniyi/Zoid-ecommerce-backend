"""Order aggregates: a placed order and its immutable snapshot lines.

An order captures the cart at checkout time: names, sizes and unit prices are
copied onto the lines so the order never changes when the catalog does. Domain
rules (a known owner, at least one line, coherent money values) live here; the
status transitions live with the workflows that trigger them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.domains.orders.domain.enums import OrderStatus
from app.shared.exceptions import ConflictError, ValidationError

#: Sentinel id for lines that have not been persisted yet.
NEW_ITEM_ID = 0


@dataclass
class OrderItem:
    """A single ordered line, snapshotted from the catalog at order time."""

    id: int
    variant_id: int
    product_slug: str
    product_name: str
    size: str
    quantity: int
    unit_price: Decimal
    currency: str = "NGN"
    image: str = ""

    @property
    def line_total(self) -> Decimal:
        return self.unit_price * self.quantity

    def validate(self) -> None:
        if not self.product_slug:
            raise ValidationError("Order item requires a product")
        if not self.size:
            raise ValidationError("Order item requires a size")
        if self.quantity < 1:
            raise ValidationError("Order item quantity must be at least 1")
        if self.unit_price < Decimal("0"):
            raise ValidationError("Order item price cannot be negative")


@dataclass
class Order:
    """An order placed by an authenticated customer."""

    id: int
    reference: str
    user_id: int
    status: OrderStatus = OrderStatus.PENDING_PAYMENT
    currency: str = "NGN"
    contact_name: str = ""
    contact_email: str = ""
    contact_phone: str = ""
    address_line: str = ""
    city_state: str = ""
    notes: str | None = None
    items: list[OrderItem] = field(default_factory=list)
    created_at: datetime | None = None

    @property
    def subtotal(self) -> Decimal:
        return sum((item.line_total for item in self.items), Decimal("0"))

    #: Shipping is not priced yet, so the amount due equals the goods subtotal.
    @property
    def total(self) -> Decimal:
        return self.subtotal

    @property
    def item_count(self) -> int:
        return sum(item.quantity for item in self.items)

    @property
    def is_pending_payment(self) -> bool:
        return self.status is OrderStatus.PENDING_PAYMENT

    def find_item(self, item_id: int) -> OrderItem | None:
        return next((item for item in self.items if item.id == item_id), None)

    def mark_paid(self) -> bool:
        """Record a confirmed payment. Returns True when this changed the order.

        Only a payment the payments domain has confirmed may move an order out of
        ``PENDING_PAYMENT``, and repeating the news is a no-op: the second
        confirmation (a webhook after a verification, say) changes nothing.
        """
        if self.status is OrderStatus.PAID:
            return False
        if not self.is_pending_payment:
            raise ConflictError(
                f"An order that is {self.status.value} cannot be paid"
            )
        self.status = OrderStatus.PAID
        return True

    def validate(self) -> None:
        if not self.reference:
            raise ValidationError("Order requires a reference")
        if self.user_id is None:
            raise ValidationError("Order requires an owning user")
        if not self.contact_name:
            raise ValidationError("Order requires a contact name")
        if not self.contact_email:
            raise ValidationError("Order requires a contact email")
        if not self.address_line:
            raise ValidationError("Order requires a delivery address")
        if not self.items:
            raise ValidationError("Order must contain at least one item")
        for item in self.items:
            item.validate()
