"""Wishlist HTTP schemas and serializers."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.domains.wishlist.domain.entities import Wishlist, WishlistItem


class WishlistItemResponse(BaseModel):
    id: int
    product_slug: str
    product_name: str
    image: str
    price: float
    currency: str


class WishlistResponse(BaseModel):
    items: list[WishlistItemResponse]
    count: int


class AddWishlistItemRequest(BaseModel):
    product_slug: str = Field(min_length=1, max_length=160)


def serialize_item(item: WishlistItem) -> WishlistItemResponse:
    return WishlistItemResponse(
        id=item.id,
        product_slug=item.product_slug,
        product_name=item.product_name,
        image=item.image,
        price=float(item.unit_price),
        currency=item.currency,
    )


def serialize_wishlist(wishlist: Wishlist) -> WishlistResponse:
    return WishlistResponse(
        items=[serialize_item(item) for item in wishlist.items],
        count=wishlist.count,
    )
