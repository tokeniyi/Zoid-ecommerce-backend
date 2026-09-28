"""The payment ledger: transactions, refunds and received provider events.

A transaction is the internal, provider-independent record of one attempt to be
paid. It owns its own state machine (pending -> paid -> refunded, or failed) so
that "did the money arrive" is a decision with one home, regardless of which
provider reported it.

A refund is the ledger of money going back, so that a payment can be refunded
more than once without ever returning more than the customer paid.

A webhook event is the receipt of a provider notification, which is what makes a
redelivery harmless instead of dangerous.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.domains.payments.domain.enums import (
    PaymentStatus,
    RefundStatus,
    WebhookKind,
)
from app.shared.exceptions import ConflictError, ValidationError


@dataclass
class Transaction:
    """A payment attempt against a single order."""

    id: int
    reference: str
    order_id: int
    amount: Decimal
    currency: str
    provider: str
    status: PaymentStatus = PaymentStatus.PENDING
    provider_reference: str | None = None
    checkout_url: str | None = None
    failure_reason: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def is_pending(self) -> bool:
        return self.status is PaymentStatus.PENDING

    @property
    def is_paid(self) -> bool:
        return self.status is PaymentStatus.PAID

    def attach_initiation(
        self, *, provider_reference: str | None, checkout_url: str | None
    ) -> None:
        """Record what the provider handed back to continue the payment."""
        if not self.is_pending:
            raise ConflictError("Only a pending transaction can be (re-)initiated")
        self.provider_reference = provider_reference or self.provider_reference
        self.checkout_url = checkout_url or self.checkout_url

    def mark_paid(self, provider_reference: str | None = None) -> None:
        """Settle the transaction. Repeating it is harmless (idempotent)."""
        if self.is_paid:
            return
        if not self.is_pending:
            raise ConflictError(
                f"A {self.status.value} transaction cannot become paid"
            )
        self.status = PaymentStatus.PAID
        if provider_reference:
            self.provider_reference = provider_reference
        self.failure_reason = None
        self.checkout_url = None

    def mark_failed(self, reason: str | None = None) -> None:
        """Abandon this attempt; a fresh transaction is needed to retry."""
        if self.is_paid:
            raise ConflictError("A paid transaction cannot be marked failed")
        self.status = PaymentStatus.FAILED
        self.failure_reason = reason or self.failure_reason or "Payment failed."

    def mark_refunded(self, provider_refund_reference: str | None = None) -> None:
        if self.status is PaymentStatus.REFUNDED:
            return
        if not self.is_paid:
            raise ConflictError("Only a paid transaction can be refunded")
        self.status = PaymentStatus.REFUNDED
        self.provider_reference = provider_refund_reference or self.provider_reference

    def validate(self) -> None:
        if not self.reference:
            raise ValidationError("Transaction requires a reference")
        if self.order_id is None:
            raise ValidationError("Transaction requires an order")
        if self.amount is None or self.amount <= Decimal("0"):
            raise ValidationError("Transaction amount must be positive")
        if not self.currency or len(self.currency) != 3:
            raise ValidationError("Transaction requires a 3-letter currency code")

    def refundable_amount(self, already_refunded: Decimal) -> Decimal:
        """What is left to give back, given what this transaction has returned."""
        remaining = self.amount - already_refunded
        if remaining <= Decimal("0"):
            raise ConflictError("This payment has already been refunded in full")
        return remaining


@dataclass
class Refund:
    """One refund of all or part of a settled payment."""

    id: int
    reference: str
    transaction_id: int
    amount: Decimal
    currency: str
    provider: str
    status: RefundStatus = RefundStatus.SUCCEEDED
    provider_refund_reference: str | None = None
    reason: str | None = None
    created_at: datetime | None = None

    @property
    def is_settled(self) -> bool:
        """Only settled refunds count against what remains refundable."""
        return self.status is RefundStatus.SUCCEEDED

    def validate(self) -> None:
        if not self.reference:
            raise ValidationError("Refund requires a reference")
        if self.transaction_id is None:
            raise ValidationError("Refund requires a transaction")
        if self.amount is None or self.amount <= Decimal("0"):
            raise ValidationError("Refund amount must be positive")
        if not self.currency or len(self.currency) != 3:
            raise ValidationError("Refund requires a 3-letter currency code")


@dataclass
class WebhookEvent:
    """A provider notification this store has taken receipt of.

    ``(provider, event_id)`` is the idempotency key: providers redeliver, and the
    second arrival of a fact is not a new fact.
    """

    id: int
    provider: str
    event_id: str
    kind: WebhookKind
    reference: str | None = None
    transaction_id: int | None = None
    processed: bool = False
    received_at: datetime | None = None

    def mark_processed(self, *, transaction_id: int | None = None) -> None:
        """Record that this notification has been acted on."""
        self.processed = True
        if transaction_id is not None:
            self.transaction_id = transaction_id

    def validate(self) -> None:
        if not self.provider:
            raise ValidationError("Webhook event requires a provider")
        if not self.event_id:
            raise ValidationError("Webhook event requires the provider's event id")
