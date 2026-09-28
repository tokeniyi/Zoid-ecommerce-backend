"""Orders HTTP schemas and serializers."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.domains.orders.domain.entities import Order, OrderItem


class CreateOrderRequest(BaseModel):
    """Delivery details collected by the checkout form."""

    contact_name: str = Field(min_length=1, max_length=120)
    contact_email: str = Field(min_length=3, max_length=320)
    contact_phone: str = Field(min_length=6, max_length=40)
    address_line: str = Field(min_length=3, max_length=300)
    city_state: str = Field(min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=500)


class OrderItemResponse(BaseModel):
    id: int
    product_slug: str
    product_name: str
    size: str
    quantity: int
    unit_price: float
    line_total: float
    image: str
    currency: str


class OrderResponse(BaseModel):
    id: int
    reference: str
    status: str
    currency: str
    subtotal: float
    total: float
    count: int
    contact_name: str
    contact_email: str
    contact_phone: str
    address_line: str
    city_state: str
    notes: str | None
    items: list[OrderItemResponse]
    created_at: datetime | None


class OrderSummaryResponse(BaseModel):
    id: int
    reference: str
    status: str
    currency: str
    total: float
    count: int
    created_at: datetime | None


def serialize_item(item: OrderItem) -> OrderItemResponse:
    return OrderItemResponse(
        id=item.id,
        product_slug=item.product_slug,
        product_name=item.product_name,
        size=item.size,
        quantity=item.quantity,
        unit_price=float(item.unit_price),
        line_total=float(item.line_total),
        image=item.image,
        currency=item.currency,
    )


def serialize_order(order: Order) -> OrderResponse:
    return OrderResponse(
        id=order.id,
        reference=order.reference,
        status=order.status.value,
        currency=order.currency,
        subtotal=float(order.subtotal),
        total=float(order.total),
        count=order.item_count,
        contact_name=order.contact_name,
        contact_email=order.contact_email,
        contact_phone=order.contact_phone,
        address_line=order.address_line,
        city_state=order.city_state,
        notes=order.notes,
        items=[serialize_item(item) for item in order.items],
        created_at=order.created_at,
    )


def serialize_order_summary(order: Order) -> OrderSummaryResponse:
    return OrderSummaryResponse(
        id=order.id,
        reference=order.reference,
        status=order.status.value,
        currency=order.currency,
        total=float(order.total),
        count=order.item_count,
        created_at=order.created_at,
    )
