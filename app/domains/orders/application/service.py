"""Orders application service.

Checkout is deliberately ordered: read the caller's cart, validate every line
against the *current* catalog (still sellable? size still offered? price still
the same?), reserve inventory, and only then persist the order as
``PENDING_PAYMENT``. Nothing here knows about a payment provider — the order is
created as unpaid and payment is a separate workflow.

The whole flow runs inside the request's unit of work, so a failure at any step
(e.g. the third line is out of stock) rolls back the earlier reservations too.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from app.domains.cart.domain.repositories import AbstractCartRepository
from app.domains.delivery.application.service import DeliveryService
from app.domains.delivery.domain.entities import DeliveryDetails, DeliveryOption, DeliveryQuote
from app.domains.orders.domain.entities import Order, OrderItem
from app.domains.orders.domain.enums import OrderStatus
from app.domains.orders.domain.repositories import AbstractOrderRepository
from app.domains.products.domain.repositories import AbstractProductRepository
from app.shared.exceptions import ConflictError, NotFoundError, ValidationError

_REFERENCE_PREFIX = "ZD-"


def new_order_reference() -> str:
    """A human-quotable, unique order reference."""
    return f"{_REFERENCE_PREFIX}{uuid4().hex[:8].upper()}"


#: Personalisation is charged on products of this style only, as on the storefront.
_PERSONALISED_STYLE = "jersey"


@dataclass(frozen=True)
class CheckoutCommand:
    """Contact and delivery details collected on the checkout form.

    There is no amount anywhere in it: delivery is priced by the server from
    where the order is going, and the goods from the catalog.
    """

    contact_name: str
    contact_email: str
    contact_phone: str
    delivery: DeliveryDetails
    notes: str | None = None


def describe_destination(details: DeliveryDetails, quote: DeliveryQuote) -> tuple[str, str]:
    """The ``(address_line, city_state)`` a packer reads off the order."""
    if details.option is DeliveryOption.PICKUP:
        return f"GUO terminal pickup: {details.terminal.strip()}", quote.state
    if quote.university:
        return f"{quote.university} — {details.hostel_room.strip()}", quote.state
    city_state = ", ".join(part for part in (quote.city, quote.state) if part)
    return details.address.strip(), city_state


class OrderService:
    def __init__(
        self,
        *,
        orders: AbstractOrderRepository,
        carts: AbstractCartRepository,
        products: AbstractProductRepository,
        delivery: DeliveryService,
        customization_fee: Decimal = Decimal("0"),
    ) -> None:
        self._orders = orders
        self._carts = carts
        self._products = products
        self._delivery = delivery
        self._customization_fee = customization_fee

    async def create_from_cart(
        self, *, user_id: int, checkout: CheckoutCommand
    ) -> Order:
        """Turn the caller's cart into a ``PENDING_PAYMENT`` order."""
        cart = await self._carts.get_by_user_id(user_id)
        if cart is None or not cart.items:
            raise ValidationError("Cannot place an order with an empty cart")

        # Price delivery first: a place the shop does not serve is refused before
        # any stock is reserved. (An "enquiry" is arranged with the shop, never
        # checked out, because there is no fee to charge.)
        quote = await self._delivery.quote(checkout.delivery)
        if not quote.is_priced:
            raise ValidationError(
                quote.message or "Delivery to this place has to be arranged with us first."
            )

        items: list[OrderItem] = []
        for line in cart.items:
            product = await self._products.get_by_slug(line.product_slug)
            if product is None or not product.is_active:
                raise ValidationError(
                    f"Product '{line.product_name}' is no longer available"
                )
            variant = next(
                (v for v in product.variants if v.id == line.variant_id), None
            )
            if variant is None or variant.size != line.size:
                raise ValidationError(
                    f"Size '{line.size}' for '{product.name}' is no longer offered"
                )
            if product.price != line.unit_price:
                raise ConflictError(
                    f"Price of '{product.name}' changed; refresh your cart"
                )
            if not await self._products.reserve_stock(variant.id, line.quantity):
                raise ConflictError(
                    f"Insufficient stock for '{product.name}' (size {line.size})"
                )
            items.append(
                OrderItem(
                    id=0,
                    variant_id=variant.id,
                    product_slug=product.slug,
                    product_name=product.name,
                    size=variant.size,
                    quantity=line.quantity,
                    unit_price=product.price,
                    currency=cart.currency,
                    image=product.primary_image or line.image,
                    customization=line.customization,
                    customization_fee=(
                        self._customization_fee
                        if line.customization
                        and product.style.strip().casefold() == _PERSONALISED_STYLE
                        else Decimal("0")
                    ),
                )
            )

        details = checkout.delivery
        address_line, city_state = describe_destination(details, quote)
        order = Order(
            id=0,
            reference=new_order_reference(),
            user_id=user_id,
            status=OrderStatus.PENDING_PAYMENT,
            currency=cart.currency,
            contact_name=checkout.contact_name,
            contact_email=checkout.contact_email,
            contact_phone=checkout.contact_phone,
            address_line=address_line,
            city_state=city_state,
            notes=checkout.notes,
            items=items,
            delivery_fee=quote.fee or Decimal("0"),
            delivery_option=quote.option.value,
            delivery_state=quote.state,
            delivery_city=quote.city,
            delivery_university=quote.university,
            delivery_hostel_room=details.hostel_room.strip() if quote.university else "",
            delivery_terminal=quote.terminal,
            delivery_terminal_pending=quote.terminal_pending,
            delivery_note=details.note.strip(),
        )
        order.validate()

        created = await self._orders.add(order)
        # The cart has been consumed by the order.
        await self._carts.delete(cart)
        return created

    async def get_for_user(self, *, user_id: int, order_id: int) -> Order:
        """Return an order, but only when it belongs to the caller."""
        order = await self._orders.get_by_id(order_id)
        if order is None or order.user_id != user_id:
            raise NotFoundError("Order not found")
        return order

    async def list_for_user(self, *, user_id: int) -> list[Order]:
        return await self._orders.list_by_user_id(user_id)
