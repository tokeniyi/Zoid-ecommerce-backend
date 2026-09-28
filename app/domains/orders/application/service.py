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
from uuid import uuid4

from app.domains.cart.domain.repositories import AbstractCartRepository
from app.domains.orders.domain.entities import Order, OrderItem
from app.domains.orders.domain.enums import OrderStatus
from app.domains.orders.domain.repositories import AbstractOrderRepository
from app.domains.products.domain.repositories import AbstractProductRepository
from app.shared.exceptions import ConflictError, NotFoundError, ValidationError

_REFERENCE_PREFIX = "ZD-"


def new_order_reference() -> str:
    """A human-quotable, unique order reference."""
    return f"{_REFERENCE_PREFIX}{uuid4().hex[:8].upper()}"


@dataclass(frozen=True)
class CheckoutCommand:
    """Delivery/contact details collected on the checkout form."""

    contact_name: str
    contact_email: str
    contact_phone: str
    address_line: str
    city_state: str
    notes: str | None = None


class OrderService:
    def __init__(
        self,
        *,
        orders: AbstractOrderRepository,
        carts: AbstractCartRepository,
        products: AbstractProductRepository,
    ) -> None:
        self._orders = orders
        self._carts = carts
        self._products = products

    async def create_from_cart(
        self, *, user_id: int, checkout: CheckoutCommand
    ) -> Order:
        """Turn the caller's cart into a ``PENDING_PAYMENT`` order."""
        cart = await self._carts.get_by_user_id(user_id)
        if cart is None or not cart.items:
            raise ValidationError("Cannot place an order with an empty cart")

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
                )
            )

        order = Order(
            id=0,
            reference=new_order_reference(),
            user_id=user_id,
            status=OrderStatus.PENDING_PAYMENT,
            currency=cart.currency,
            contact_name=checkout.contact_name,
            contact_email=checkout.contact_email,
            contact_phone=checkout.contact_phone,
            address_line=checkout.address_line,
            city_state=checkout.city_state,
            notes=checkout.notes,
            items=items,
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
