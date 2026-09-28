"""Orders HTTP endpoints (authenticated only).

Checkout is an authenticated workflow: the order is built from the caller's
server-side cart and owned by their session identity, never by an id supplied
in the request. Created orders come back as ``PENDING_PAYMENT`` — payment is a
separate step.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.domains.orders.api.schemas import (
    CreateOrderRequest,
    OrderResponse,
    OrderSummaryResponse,
    serialize_order,
    serialize_order_summary,
)
from app.domains.orders.application.service import CheckoutCommand, OrderService
from app.infrastructure.container import get_order_service
from app.security.authorization import Principal, require_authenticated_user

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    body: CreateOrderRequest,
    principal: Annotated[Principal, Depends(require_authenticated_user)],
    service: Annotated[OrderService, Depends(get_order_service)],
) -> OrderResponse:
    """Check out the caller's cart as a new pending-payment order."""
    order = await service.create_from_cart(
        user_id=principal.user_id,
        checkout=CheckoutCommand(
            contact_name=body.contact_name,
            contact_email=body.contact_email,
            contact_phone=body.contact_phone,
            address_line=body.address_line,
            city_state=body.city_state,
            notes=body.notes,
        ),
    )
    return serialize_order(order)


@router.get("", response_model=list[OrderSummaryResponse])
async def list_orders(
    principal: Annotated[Principal, Depends(require_authenticated_user)],
    service: Annotated[OrderService, Depends(get_order_service)],
) -> list[OrderSummaryResponse]:
    """Return the caller's orders, newest first."""
    orders = await service.list_for_user(user_id=principal.user_id)
    return [serialize_order_summary(order) for order in orders]


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: int,
    principal: Annotated[Principal, Depends(require_authenticated_user)],
    service: Annotated[OrderService, Depends(get_order_service)],
) -> OrderResponse:
    """Return one of the caller's orders (other people's orders are not found)."""
    order = await service.get_for_user(user_id=principal.user_id, order_id=order_id)
    return serialize_order(order)
