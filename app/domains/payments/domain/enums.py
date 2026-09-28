"""Payment, refund and webhook vocabulary.

These are *payment* concerns and deliberately separate from order status: an
order can stay ``PENDING_PAYMENT`` while a transaction is ``pending``, and a
verified transaction becomes ``paid`` regardless of which provider produced the
answer.
"""

from __future__ import annotations

from enum import StrEnum


class PaymentStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class PaymentAction(StrEnum):
    """What the client must do next to complete a payment."""

    REDIRECT = "redirect"


class RefundStatus(StrEnum):
    """Where one refund stands. Only settled money counts against the balance."""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class WebhookKind(StrEnum):
    """The provider-independent meaning of an inbound provider event.

    Each adapter translates its own event names into one of these. Anything a
    provider tells us that has no business meaning here stays ``IGNORED``: it is
    still recorded, and it still changes nothing.
    """

    PAYMENT_PAID = "payment_paid"
    PAYMENT_FAILED = "payment_failed"
    REFUND_SETTLED = "refund_settled"
    IGNORED = "ignored"


class WebhookOutcome(StrEnum):
    """What the application did with an event it accepted."""

    APPLIED = "applied"
    DUPLICATE = "duplicate"
    UNMATCHED = "unmatched"
    IGNORED = "ignored"
    #: The event said something this ledger disagrees with. Recorded, not acted on.
    DISPUTED = "disputed"
