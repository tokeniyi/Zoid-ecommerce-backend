"""Cart HTTP endpoints.

Public for guests (identified by the ``guest_cart_id`` cookie) and scoped to the
session for authenticated shoppers. Every operation resolves the cart from the
request, never from a caller-supplied id, so cross-cart access is impossible.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.domains.cart.api.deps import (
    GUEST_CART_COOKIE,
    CartLocation,
    attach_guest_cookie,
    clear_guest_cookie,
    get_cart_location,
)
from app.domains.cart.api.schemas import (
    AddItemRequest,
    CartResponse,
    UpdateItemRequest,
    serialize_cart,
)
from app.domains.cart.application.service import CartService
from app.infrastructure.container import get_cart_service
from app.security.authorization import Principal, require_authenticated_user

router = APIRouter(tags=["cart"])


@router.get("/cart", response_model=CartResponse)
async def read_cart(
    location: Annotated[CartLocation, Depends(get_cart_location)],
    response: Response,
    service: Annotated[CartService, Depends(get_cart_service)],
) -> CartResponse:
    cart = await service.ensure_cart(user_id=location.user_id, guest_token=location.guest_token)
    attach_guest_cookie(response, location, cart.guest_token)
    return serialize_cart(cart)


@router.post("/cart/items", response_model=CartResponse)
async def add_item(
    body: AddItemRequest,
    location: Annotated[CartLocation, Depends(get_cart_location)],
    response: Response,
    service: Annotated[CartService, Depends(get_cart_service)],
) -> CartResponse:
    cart = await service.ensure_cart(user_id=location.user_id, guest_token=location.guest_token)
    attach_guest_cookie(response, location, cart.guest_token)
    cart = await service.add_item(
        cart, product_slug=body.product_slug, size=body.size, quantity=body.quantity
    )
    return serialize_cart(cart)


@router.patch("/cart/items/{item_id}", response_model=CartResponse)
async def update_item(
    item_id: int,
    body: UpdateItemRequest,
    location: Annotated[CartLocation, Depends(get_cart_location)],
    response: Response,
    service: Annotated[CartService, Depends(get_cart_service)],
) -> CartResponse:
    cart = await service.ensure_cart(user_id=location.user_id, guest_token=location.guest_token)
    attach_guest_cookie(response, location, cart.guest_token)
    cart = await service.update_item(cart, item_id, body.quantity)
    return serialize_cart(cart)


@router.delete("/cart/items/{item_id}", response_model=CartResponse)
async def remove_item(
    item_id: int,
    location: Annotated[CartLocation, Depends(get_cart_location)],
    response: Response,
    service: Annotated[CartService, Depends(get_cart_service)],
) -> CartResponse:
    cart = await service.ensure_cart(user_id=location.user_id, guest_token=location.guest_token)
    attach_guest_cookie(response, location, cart.guest_token)
    cart = await service.remove_item(cart, item_id)
    return serialize_cart(cart)


@router.post("/cart/merge", response_model=CartResponse)
async def merge_guest_cart(
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(require_authenticated_user)],
    service: Annotated[CartService, Depends(get_cart_service)],
) -> CartResponse:
    guest_token = request.cookies.get(GUEST_CART_COOKIE)
    if not guest_token:
        cart = await service.ensure_cart(user_id=principal.user_id, guest_token=None)
        return serialize_cart(cart)
    cart = await service.merge_guest_into_user(user_id=principal.user_id, guest_token=guest_token)
    clear_guest_cookie(response)
    return serialize_cart(cart)
