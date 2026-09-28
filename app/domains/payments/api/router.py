"""Payments HTTP endpoints.

Initiation and verification are customer operations on their own orders; refunds
are an order-management permission. No endpoint here knows which provider is
configured -- the response shape is the normalized contract in all cases.

The webhook endpoint is the exception to that auth pattern, because a provider
cannot hold a customer session; it is authenticated by signature instead.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.domains.payments.api.schemas import (
    InitiatePaymentRequest,
    PaymentResponse,
    RefundPaymentRequest,
    VerifyPaymentRequest,
    WebhookResponse,
    serialize_initiation,
    serialize_refund,
    serialize_verification,
    serialize_webhook,
)
from app.domains.payments.application.service import PaymentService
from app.infrastructure.container import get_payment_service
from app.security.authorization import (
    Permission,
    Principal,
    require_authenticated_user,
    require_permission,
)

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/initiate", response_model=PaymentResponse)
async def initiate_payment(
    body: InitiatePaymentRequest,
    principal: Annotated[Principal, Depends(require_authenticated_user)],
    service: Annotated[PaymentService, Depends(get_payment_service)],
) -> PaymentResponse:
    """Start payment for one of the caller's pending orders."""
    transaction, initiation = await service.initiate(
        user_id=principal.user_id, order_id=body.order_id
    )
    return serialize_initiation(transaction, initiation)


@router.post("/verify", response_model=PaymentResponse)
async def verify_payment(
    body: VerifyPaymentRequest,
    principal: Annotated[Principal, Depends(require_authenticated_user)],
    service: Annotated[PaymentService, Depends(get_payment_service)],
) -> PaymentResponse:
    """Confirm a payment with the provider; the client's word is not accepted."""
    transaction, verification = await service.verify(
        user_id=principal.user_id, reference=body.reference
    )
    return serialize_verification(transaction, verification)


@router.post("/refunds", response_model=PaymentResponse)
async def refund_payment(
    body: RefundPaymentRequest,
    _: Annotated[Principal, Depends(require_permission(Permission.MANAGE_ORDERS))],
    service: Annotated[PaymentService, Depends(get_payment_service)],
) -> PaymentResponse:
    """Refund a settled payment (admin/order-management only)."""
    amount = Decimal(str(body.amount)) if body.amount is not None else None
    transaction, refund = await service.refund(
        reference=body.reference, amount=amount, reason=body.reason
    )
    return serialize_refund(transaction, refund)


@router.post("/webhooks/{provider}", response_model=WebhookResponse)
async def payment_webhook(
    provider: str,
    request: Request,
    service: Annotated[PaymentService, Depends(get_payment_service)],
) -> WebhookResponse:
    """Receive a provider notification about a payment.

    There is no session here to depend on, so the raw body is passed to the
    adapter that knows how to authenticate it: an unsigned or badly signed
    notification is refused before anything reads what it claims. A genuine one
    is answered the same way whether it changed anything or was a redelivery,
    because a provider that sees a retry-worthy failure will keep retrying news
    we have already acted on.
    """
    payload = await request.body()
    _, outcome = await service.handle_webhook(
        provider=provider, payload=payload, headers=request.headers
    )
    return serialize_webhook(outcome)
