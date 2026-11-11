"""Orders HTTP schemas and serializers."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.domains.delivery.api.schemas import DeliveryRequest
from app.domains.orders.domain.entities import Order, OrderItem
from app.shared.money import serialize_money


class CreateOrderRequest(BaseModel):
    """Contact and delivery details collected by the checkout form.

    No amounts: delivery and personalisation are priced by the server.
    """

    contact_name: str = Field(min_length=1, max_length=120)
    contact_email: str = Field(min_length=3, max_length=320)
    contact_phone: str = Field(min_length=6, max_length=40)
    delivery: DeliveryRequest
    notes: str | None = Field(default=None, max_length=500)


class OrderItemResponse(BaseModel):
    id: int
    product_slug: str
    product_name: str
    size: str
    quantity: int
    unit_price: str
    line_total: str
    image: str
    currency: str
    customization: str
    customization_fee: str


class OrderDeliveryResponse(BaseModel):
    option: str
    fee: str
    state: str
    city: str
    university: str
    hostel_room: str
    terminal: str
    terminal_pending: bool
    note: str
    is_student: bool


class OrderResponse(BaseModel):
    id: int
    reference: str
    status: str
    currency: str
    #: The goods alone; ``total`` = subtotal + customization_total + delivery.fee.
    subtotal: str
    customization_total: str
    total: str
    count: int
    delivery: OrderDeliveryResponse
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
    total: str
    count: int
    created_at: datetime | None


def serialize_item(item: OrderItem) -> OrderItemResponse:
    return OrderItemResponse(
        id=item.id,
        product_slug=item.product_slug,
        product_name=item.product_name,
        size=item.size,
        quantity=item.quantity,
        unit_price=serialize_money(item.unit_price),
        line_total=serialize_money(item.line_total),
        image=item.image,
        currency=item.currency,
        customization=item.customization,
        customization_fee=serialize_money(item.customization_fee),
    )


def serialize_order(order: Order) -> OrderResponse:
    return OrderResponse(
        id=order.id,
        reference=order.reference,
        status=order.status.value,
        currency=order.currency,
        subtotal=serialize_money(order.subtotal),
        customization_total=serialize_money(order.customization_total),
        total=serialize_money(order.total),
        count=order.item_count,
        delivery=OrderDeliveryResponse(
            option=order.delivery_option,
            fee=serialize_money(order.delivery_fee),
            state=order.delivery_state,
            city=order.delivery_city,
            university=order.delivery_university,
            hostel_room=order.delivery_hostel_room,
            terminal=order.delivery_terminal,
            terminal_pending=order.delivery_terminal_pending,
            note=order.delivery_note,
            is_student=order.is_student,
        ),
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
        total=serialize_money(order.total),
        count=order.item_count,
        created_at=order.created_at,
    )
