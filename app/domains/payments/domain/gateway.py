"""The payment gateway contract.

This is the single seam between the application and *any* payment provider. It
is expressed in business capabilities -- create, verify, refund -- and
normalised results, never in provider payloads: what comes back is "a payment
was initiated" plus what the client needs to continue, not a Paystack
``authorization_url`` or a Stripe session object. Adapters (Paystack, Stripe,
selected by configuration) live outside this module and translate in both
directions.

A webhook/signature capability is added with the confirmation workflow, so this
contract stays limited to what the application can do today.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from app.domains.payments.domain.enums import PaymentAction, PaymentStatus


@dataclass(frozen=True)
class PaymentRequest:
    """What the application asks a provider to charge."""

    reference: str
    amount: Decimal
    currency: str
    email: str
    order_reference: str
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PaymentInitiation:
    """Normalised outcome of asking a provider to start a payment."""

    success: bool
    status: PaymentStatus
    transaction_reference: str | None = None
    provider_reference: str | None = None
    checkout_url: str | None = None
    action: PaymentAction | None = None
    message: str | None = None

    @property
    def next_action(self) -> tuple[PaymentAction, str] | None:
        """The (action, url) pair a client needs, when there is one."""
        if self.action is None or not self.checkout_url:
            return None
        return self.action, self.checkout_url


@dataclass(frozen=True)
class PaymentVerification:
    """Normalised outcome of asking a provider whether a payment succeeded.

    ``success`` answers "did the check work"; ``status`` answers "did the money
    arrive". They are kept apart on purpose: a provider can answer confidently
    that a payment failed.
    """

    success: bool
    status: PaymentStatus
    transaction_reference: str | None = None
    provider_reference: str | None = None
    amount: Decimal | None = None
    message: str | None = None


@dataclass(frozen=True)
class RefundRequest:
    """What the application asks a provider to give back."""

    transaction_reference: str
    amount: Decimal | None = None
    reason: str | None = None


@dataclass(frozen=True)
class RefundResult:
    success: bool
    status: PaymentStatus
    transaction_reference: str | None = None
    provider_refund_reference: str | None = None
    amount: Decimal | None = None
    message: str | None = None


class AbstractPaymentGateway(ABC):
    """Provider-independent payment capability."""

    #: Short, stable identifier of the implementation ("paystack", "stripe").
    provider: str = "none"

    @abstractmethod
    async def create_payment(self, request: PaymentRequest) -> PaymentInitiation:
        """Start a payment and report how the customer continues it."""

    @abstractmethod
    async def verify_payment(self, reference: str) -> PaymentVerification:
        """Ask the provider about ``reference`` and normalise the answer."""

    @abstractmethod
    async def refund_payment(self, request: RefundRequest) -> RefundResult:
        """Refund all or part of a settled payment."""
