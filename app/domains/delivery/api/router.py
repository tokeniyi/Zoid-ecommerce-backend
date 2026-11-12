"""Delivery HTTP routes.

``POST /delivery/quote`` is public and changes nothing: it lets the checkout show
the delivery fee (or "ask us") before the customer commits to anything.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.config import get_settings
from app.domains.delivery.api.schemas import (
    DeliveryQuoteResponse,
    DeliveryRequest,
    serialize_quote,
)
from app.domains.delivery.application.service import DeliveryService
from app.infrastructure.container import get_delivery_service

router = APIRouter(tags=["delivery"])


@router.post("/delivery/quote", response_model=DeliveryQuoteResponse)
async def quote_delivery(
    body: DeliveryRequest,
    service: Annotated[DeliveryService, Depends(get_delivery_service)],
) -> DeliveryQuoteResponse:
    """What delivering to this place costs, as the server prices it.

    A place the shop does not serve is not an error: the answer is
    ``support_required: true`` with no fee, so the checkout can offer terminal
    pickup or point the customer at the shop.
    """
    details = body.to_details()
    quote = await service.quote(details)
    return serialize_quote(
        quote, currency=get_settings().payment_currency, is_student=details.is_student
    )
