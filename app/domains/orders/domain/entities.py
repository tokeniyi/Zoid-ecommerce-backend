"""Order aggregates: a placed order and its immutable snapshot lines.

An order captures the cart at checkout time: names, sizes and unit prices are
copied onto the lines so the order never changes when the catalog does. Domain
rules (a known owner, at least one line, coherent money values) live here; the
status transitions live with the workflows that trigger them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from app.domains.orders.domain.enums import FulfillmentStatus, OrderPaymentStatus, OrderStatus
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
    #: Personalisation copied from the cart line ("" when none).
    customization: str = ""
    #: What personalising *one* unit cost at checkout (0 when not personalised or
    #: when the product is not charged for it). A snapshot, like the unit price.
    customization_fee: Decimal = Decimal("0")

    @property
    def line_total(self) -> Decimal:
        return self.unit_price * self.quantity

    @property
    def customization_total(self) -> Decimal:
        return self.customization_fee * self.quantity

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
    #: What delivery cost, as the server priced it at checkout.
    delivery_fee: Decimal = Decimal("0")
    # How the order is to reach the customer (see the delivery domain).
    delivery_option: str = ""
    delivery_state: str = ""
    delivery_city: str = ""
    delivery_university: str = ""
    delivery_hostel_room: str = ""
    delivery_terminal: str = ""
    delivery_terminal_pending: bool = False
    delivery_note: str = ""
    #: The parcel's progress; only meaningful once the order is paid.
    fulfillment_status: FulfillmentStatus = FulfillmentStatus.PROCESSING
    #: The reference of the payment that settled this order, once there is one.
    payment_reference: str | None = None
    paid_at: datetime | None = None

    @property
    def subtotal(self) -> Decimal:
        """The goods alone, before personalisation and delivery."""
        return sum((item.line_total for item in self.items), Decimal("0"))

    @property
    def customization_total(self) -> Decimal:
        return sum((item.customization_total for item in self.items), Decimal("0"))

    @property
    def total(self) -> Decimal:
        """What the customer pays: goods + personalisation + delivery."""
        return self.subtotal + self.customization_total + self.delivery_fee

    @property
    def is_student(self) -> bool:
        """Delivered to a campus."""
        return bool(self.delivery_university)

    @property
    def item_count(self) -> int:
        return sum(item.quantity for item in self.items)

    @property
    def is_pending_payment(self) -> bool:
        return self.status is OrderStatus.PENDING_PAYMENT

    @property
    def payment_status(self) -> OrderPaymentStatus:
        """Paid, still waiting, or cancelled — the payment side, on its own."""
        if self.status is OrderStatus.PENDING_PAYMENT:
            return OrderPaymentStatus.PENDING
        if self.status is OrderStatus.CANCELLED:
            return OrderPaymentStatus.CANCELLED
        return OrderPaymentStatus.PAID

    def set_fulfillment(self, status: FulfillmentStatus) -> bool:
        """Move the parcel along. Returns True when this changed anything.

        Only a paid order can be fulfilled: the shop does not ship what nobody has
        paid for. Any stage may be corrected to any other (the shop sometimes
        taps the wrong one), so the only rule here is about payment.
        """
        if self.payment_status is not OrderPaymentStatus.PAID:
            raise ConflictError(
                f"An order that is {self.payment_status.value} cannot be fulfilled"
            )
        if self.fulfillment_status is status:
            return False
        self.fulfillment_status = status
        return True

    def confirm_terminal(self, terminal: str) -> None:
        """Settle which GUO terminal a pickup order goes to.

        Customers may name a terminal the shop has not verified; the shop then
        confirms (or corrects) it here.
        """
        if self.delivery_option != "pickup":
            raise ConflictError("Only a pickup order has a terminal to confirm")
        if not terminal.strip():
            raise ValidationError("A terminal name is required")
        self.delivery_terminal = terminal.strip()
        self.delivery_terminal_pending = False
        self.address_line = f"GUO terminal pickup: {self.delivery_terminal}"

    def find_item(self, item_id: int) -> OrderItem | None:
        return next((item for item in self.items if item.id == item_id), None)

    def mark_paid(self, reference: str | None = None, at: datetime | None = None) -> bool:
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
        self.payment_reference = reference
        self.paid_at = at or datetime.now(UTC)
        return True

    def validate(self) -> None:
        if not self.reference:
            raise ValidationError("Order requires a reference")
        if self.user_id is None:
            raise ValidationError("Order requires an owning user")
        if self.delivery_fee < 0:
            raise ValidationError("Delivery fee cannot be negative")
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
