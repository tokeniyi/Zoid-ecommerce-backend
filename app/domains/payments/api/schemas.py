"""Payments HTTP schemas and serializers.

The body a client receives is the architecture's normalised payment result:
``success``/``status`` plus a ``next_action`` describing how to continue. Whether
the URL behind that action came from Paystack or Stripe is not expressible here.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.domains.payments.domain.entities import Transaction
from app.domains.payments.domain.enums import WebhookOutcome
from app.domains.payments.domain.gateway import (
    PaymentInitiation,
    PaymentVerification,
    RefundResult,
)


class InitiatePaymentRequest(BaseModel):
    order_id: int


class VerifyPaymentRequest(BaseModel):
    reference: str = Field(min_length=6, max_length=64)


class RefundPaymentRequest(BaseModel):
    reference: str = Field(min_length=6, max_length=64)
    amount: float | None = Field(default=None, gt=0)
    reason: str | None = Field(default=None, max_length=300)


class NextActionResponse(BaseModel):
    type: str
    url: str


class PaymentResponse(BaseModel):
    success: bool
    payment_id: str
    status: str
    amount: float
    currency: str
    provider: str
    order_id: int
    next_action: NextActionResponse | None = None
    message: str | None = None


class WebhookResponse(BaseModel):
    """A receipt for a provider notification.

    Deliberately thin. The purpose of the answer is that the provider stops
    retrying, not that it learns how this shop's ledger is arranged; the outcome
    says what *we* did with the event, in our own vocabulary.
    """

    received: bool = True
    outcome: str


def _next_action(
    initiation: PaymentInitiation, transaction: Transaction
) -> NextActionResponse | None:
    action = initiation.next_action
    if action is not None:
        return NextActionResponse(type=action[0].value, url=action[1])
    if transaction.checkout_url:
        return NextActionResponse(type="redirect", url=transaction.checkout_url)
    return None


def serialize_initiation(
    transaction: Transaction, initiation: PaymentInitiation
) -> PaymentResponse:
    return PaymentResponse(
        success=initiation.success,
        payment_id=transaction.reference,
        status=transaction.status.value,
        amount=float(transaction.amount),
        currency=transaction.currency,
        provider=transaction.provider,
        order_id=transaction.order_id,
        next_action=_next_action(initiation, transaction),
        message=initiation.message,
    )


def serialize_verification(
    transaction: Transaction, verification: PaymentVerification
) -> PaymentResponse:
    return PaymentResponse(
        success=verification.success,
        payment_id=transaction.reference,
        status=transaction.status.value,
        amount=float(transaction.amount),
        currency=transaction.currency,
        provider=transaction.provider,
        order_id=transaction.order_id,
        message=verification.message,
    )


def serialize_refund(transaction: Transaction, refund: RefundResult) -> PaymentResponse:
    return PaymentResponse(
        success=refund.success,
        payment_id=transaction.reference,
        status=transaction.status.value,
        amount=float(refund.amount if refund.amount is not None else transaction.amount),
        currency=transaction.currency,
        provider=transaction.provider,
        order_id=transaction.order_id,
        message=refund.message,
    )


def serialize_webhook(outcome: WebhookOutcome) -> WebhookResponse:
    return WebhookResponse(outcome=outcome.value)
