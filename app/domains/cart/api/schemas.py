"""Cart HTTP schemas and serializers."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.domains.cart.domain.entities import Cart, CartItem
from app.shared.money import serialize_money


class CartItemResponse(BaseModel):
    id: int
    product_slug: str
    product_name: str
    size: str
    quantity: int
    unit_price: str
    line_total: str
    image: str
    currency: str


class CartResponse(BaseModel):
    items: list[CartItemResponse]
    count: int
    total: str
    currency: str


class AddItemRequest(BaseModel):
    product_slug: str = Field(min_length=1, max_length=160)
    size: str = Field(min_length=1, max_length=20)
    quantity: int = Field(default=1, ge=1, le=99)


class UpdateItemRequest(BaseModel):
    quantity: int = Field(ge=1, le=99)


def serialize_item(item: CartItem) -> CartItemResponse:
    return CartItemResponse(
        id=item.id,
        product_slug=item.product_slug,
        product_name=item.product_name,
        size=item.size,
        quantity=item.quantity,
        unit_price=serialize_money(item.unit_price),
        line_total=serialize_money(item.line_total),
        image=item.image,
        currency=item.currency,
    )


def serialize_cart(cart: Cart) -> CartResponse:
    return CartResponse(
        items=[serialize_item(item) for item in cart.items],
        count=cart.count,
        total=serialize_money(cart.total),
        currency=cart.currency,
    )
