"""Stripe adapter.

Everything Stripe-specific is confined here: Checkout Sessions, minor-unit
amounts, payment-intent statuses, refund reason enums, and the SDK's exception
hierarchy. The application sees only the payment contract.

Notes on two details that are easy to get wrong:

* The SDK client is blocking, so every call is offloaded with
  ``asyncio.to_thread`` -- the event loop never waits on Stripe.
* Stripe hands back its own session id, not our reference, so verification finds
  the payment by the metadata we attach at creation time. A refund needs the
  payment intent for the same reason.

* Webhook signatures are checked by Stripe's own verification code, which is the
  only implementation that knows Stripe's signing scheme, timestamp tolerance and
  revocation rules.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import stripe

from app.domains.payments.domain.enums import (
    PaymentAction,
    PaymentStatus,
    WebhookKind,
)
from app.domains.payments.domain.gateway import (
    AbstractPaymentGateway,
    PaymentInitiation,
    PaymentRequest,
    PaymentVerification,
    RefundRequest,
    RefundResult,
)
from app.domains.payments.domain.webhooks import (
    AbstractWebhookAdapter,
    WebhookNotification,
)
from app.shared.exceptions import (
    ProviderNotConfiguredError,
    SignatureVerificationError,
    ValidationError,
)

#: The header Stripe signs its notifications into.
SIGNATURE_HEADER = "stripe-signature"

#: The metadata key our internal reference is carried under. Stripe does not
#: accept a merchant reference of its own on a Checkout Session.
REFERENCE_KEY = "reference"
ORDER_REFERENCE_KEY = "order_reference"

#: Currencies Stripe bills in whole units. Charging these x100 would be a 100x
#: overcharge, so the conversion has to know about them.
_ZERO_DECIMAL_CURRENCIES = frozenset(
    {"djf", "gnf", "jpy", "kmf", "krw", "pyg", "vnd", "xaf", "xof", "xpf"}
)

#: Stripe's refund ``reason`` is a fixed enum; anything else is carried as
#: metadata so a human note is never rejected.
_REFUND_REASONS = frozenset({"duplicate", "fraudulent", "requested_by_customer"})

_INTENT_STATUSES = {
    "succeeded": PaymentStatus.PAID,
    "requires_payment_method": PaymentStatus.FAILED,
    "requires_action": PaymentStatus.PENDING,
    "processing": PaymentStatus.PENDING,
    "canceled": PaymentStatus.FAILED,
}

#: Stripe's event types, translated into what this shop does about them. A
#: Checkout Session completing is the same news as a payment intent succeeding,
#: and both mean the same thing to us as Paystack's ``charge.success``.
_EVENT_KINDS = {
    "checkout.session.completed": WebhookKind.PAYMENT_PAID,
    "payment_intent.succeeded": WebhookKind.PAYMENT_PAID,
    "charge.succeeded": WebhookKind.PAYMENT_PAID,
    "checkout.session.expired": WebhookKind.PAYMENT_FAILED,
    "payment_intent.payment_failed": WebhookKind.PAYMENT_FAILED,
    "charge.failed": WebhookKind.PAYMENT_FAILED,
    "charge.dispute.created": WebhookKind.PAYMENT_FAILED,
    "charge.refunded": WebhookKind.REFUND_SETTLED,
    "refund.created": WebhookKind.REFUND_SETTLED,
}


def _to_minor_units(amount: Decimal, currency: str) -> int:
    multiplier = Decimal(1) if currency.lower() in _ZERO_DECIMAL_CURRENCIES else Decimal(100)
    return int((amount * multiplier).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _from_minor_units(amount: Any, currency: str) -> Decimal | None:
    if not isinstance(amount, int):
        return None
    multiplier = Decimal(1) if currency.lower() in _ZERO_DECIMAL_CURRENCIES else Decimal(100)
    return (Decimal(amount) / multiplier).quantize(Decimal("0.01"))


class StripePaymentGateway(AbstractPaymentGateway, AbstractWebhookAdapter):
    """The payment contract, spoken to Stripe -- in both directions."""

    provider = "stripe"

    def __init__(
        self,
        *,
        secret_key: str,
        return_url: str = "",
        webhook_secret: str = "",
        client: Any | None = None,
    ) -> None:
        self._secret_key = secret_key
        self._return_url = return_url.rstrip("/")
        self._webhook_secret = webhook_secret
        # Injectable so the adapter can be tested without a network or an SDK
        # version dependency; production builds it from the secret key.
        self._client = client

    async def create_payment(self, request: PaymentRequest) -> PaymentInitiation:
        params: dict[str, Any] = {
            "mode": "payment",
            "customer_email": request.email,
            "success_url": self._return_to(request, "completed"),
            "cancel_url": self._return_to(request, "cancelled"),
            "client_reference_id": request.reference,
            "line_items": [
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": request.currency.lower(),
                        "unit_amount": _to_minor_units(request.amount, request.currency),
                        "product_data": {
                            "name": f"Zoid order {request.order_reference}"
                        },
                    },
                }
            ],
            "metadata": {
                REFERENCE_KEY: request.reference,
                ORDER_REFERENCE_KEY: request.order_reference,
            },
        }
        try:
            session = await self._request(self._api().checkout.sessions.create, params)
        except stripe.APIConnectionError:
            return self._unreachable_initiation(request)
        except stripe.StripeError as exc:
            return PaymentInitiation(
                success=False,
                status=PaymentStatus.FAILED,
                transaction_reference=request.reference,
                message=str(exc),
            )

        checkout_url = getattr(session, "url", None)
        if not checkout_url:
            return self._unreachable_initiation(request)

        return PaymentInitiation(
            success=True,
            status=PaymentStatus.PENDING,
            transaction_reference=request.reference,
            provider_reference=_as_text(getattr(session, "id", None)),
            checkout_url=str(checkout_url),
            action=PaymentAction.REDIRECT,
        )

    async def verify_payment(self, reference: str) -> PaymentVerification:
        try:
            intent = await self._find_intent(reference)
        except stripe.APIConnectionError:
            return PaymentVerification(
                success=False,
                status=PaymentStatus.PENDING,
                transaction_reference=reference,
                message="Could not reach Stripe.",
            )
        except stripe.StripeError as exc:
            return PaymentVerification(
                success=False,
                status=PaymentStatus.PENDING,
                transaction_reference=reference,
                message=str(exc),
            )

        if intent is None:
            # Stripe knows nothing about it: the customer has not finished (or
            # never opened) the hosted checkout. That is an honest "not yet",
            # never a failure.
            return PaymentVerification(
                success=True,
                status=PaymentStatus.PENDING,
                transaction_reference=reference,
                message="Stripe has no payment for this reference yet.",
            )

        answer = str(getattr(intent, "status", "") or "")
        amount = _from_minor_units(
            getattr(intent, "amount_received", None), str(getattr(intent, "currency", "") or "")
        )
        return PaymentVerification(
            success=True,
            status=_INTENT_STATUSES.get(answer, PaymentStatus.PENDING),
            transaction_reference=reference,
            provider_reference=_as_text(getattr(intent, "id", None)),
            amount=amount,
            message=_failure_message(intent),
        )

    async def refund_payment(self, request: RefundRequest) -> RefundResult:
        try:
            intent = await self._find_intent(request.transaction_reference)
        except stripe.StripeError as exc:
            return self._refund_problem(request, str(exc))
        if intent is None:
            return self._refund_problem(
                request, "Stripe has no payment to refund for this reference."
            )

        intent_id = getattr(intent, "id", None)
        if not intent_id:
            return self._refund_problem(request, "Stripe returned a payment without an id.")

        params: dict[str, Any] = {"payment_intent": str(intent_id)}
        if request.amount is not None:
            params["amount"] = _to_minor_units(request.amount, self._currency_of(intent))
        note = (request.reason or "").strip()
        if note:
            # Admins write prose, Stripe wants an enum. Use the enum when the
            # words match one; never lose a note just because it is not a code.
            key = "_".join(note.lower().split())
            if key in _REFUND_REASONS:
                params["reason"] = key
            else:
                params["metadata"] = {"reason": note}

        try:
            refund = await self._request(self._api().refunds.create, params)
        except stripe.APIConnectionError:
            return self._refund_problem(request, "Could not reach Stripe.")
        except stripe.StripeError as exc:
            return self._refund_problem(request, str(exc))

        outcome = str(getattr(refund, "status", "") or "")
        if outcome and outcome != "succeeded":
            return self._refund_problem(request, f"Stripe reported the refund as {outcome}.")

        amount = _from_minor_units(
            getattr(refund, "amount", None), str(getattr(refund, "currency", "") or "")
        )
        return RefundResult(
            success=True,
            status=PaymentStatus.REFUNDED,
            transaction_reference=request.transaction_reference,
            provider_refund_reference=_as_text(getattr(refund, "id", None)),
            amount=amount if amount is not None else request.amount,
        )

    # --- webhook intake ------------------------------------------------------

    def parse_notification(
        self, *, payload: bytes, headers: Mapping[str, str]
    ) -> WebhookNotification:
        """Verify Stripe's signature, then normalise the event.

        Verification is Stripe's own code, handed the raw body: Stripe signs the
        bytes it sent, so anything that re-serialises the JSON on the way invalidates
        an honest notification. Without the signing secret there is no way to tell a
        real event from a forged one, so the adapter refuses instead of guessing.
        """
        if not self._webhook_secret:
            raise ProviderNotConfiguredError(
                "Stripe notifications cannot be verified without "
                "STRIPE_WEBHOOK_SECRET."
            )
        claimed = str(headers.get(SIGNATURE_HEADER) or "")
        if not claimed:
            raise SignatureVerificationError("Stripe signature verification failed.")
        try:
            event = stripe.Webhook.construct_event(
                payload, claimed, self._webhook_secret
            )
        except stripe.SignatureVerificationError as exc:
            raise SignatureVerificationError(
                "Stripe signature verification failed."
            ) from exc
        except (ValueError, TypeError) as exc:
            # Authenticated, but not something this shop can read.
            raise ValidationError("Stripe sent an event this store cannot read") from exc

        event_id = str(_read(event, "id") or "").strip()
        if not event_id:
            raise ValidationError("Stripe sent an event with no id to identify it by")
        name = str(_read(event, "type") or "").strip().lower()
        obj = _read(event, "data.object")
        currency = str(_read(obj, "currency") or "")
        return WebhookNotification(
            provider=self.provider,
            event_id=event_id,
            kind=_EVENT_KINDS.get(name, WebhookKind.IGNORED),
            reference=_reference_from(obj),
            provider_reference=_as_text(_read(obj, "id")),
            amount=_from_minor_units(_reported_amount(obj), currency),
            message=_failure_message(obj) or _as_text(_read(obj, "failure_message")),
        )

    async def _find_intent(self, reference: str) -> Any | None:
        """The payment intent behind one of our references, if there is one."""
        page = await self._request(
            self._api().payment_intents.search,
            {"query": f"metadata['{REFERENCE_KEY}']:'{reference}'", "limit": 1},
        )
        found = list(getattr(page, "data", None) or [])
        return found[0] if found else None

    async def _request(self, call: Callable[..., Any], params: dict[str, Any]) -> Any:
        """One SDK call, off the event loop."""
        return await asyncio.to_thread(call, **params)

    def _api(self) -> Any:
        """The Stripe service surface, built on first use from configuration."""
        if self._client is None:
            if not self._secret_key:
                raise ProviderNotConfiguredError(
                    "Payment provider 'stripe' is selected but STRIPE_SECRET_KEY "
                    "is not configured."
                )
            self._client = stripe.StripeClient(api_key=self._secret_key)
        return self._client.v1

    def _return_to(self, request: PaymentRequest, outcome: str) -> str:
        separator = "&" if "?" in self._return_url else "?"
        return f"{self._return_url}{separator}{outcome}=1&reference={request.reference}"

    def _unreachable_initiation(self, request: PaymentRequest) -> PaymentInitiation:
        return PaymentInitiation(
            success=False,
            status=PaymentStatus.PENDING,
            transaction_reference=request.reference,
            message="Could not reach Stripe.",
        )

    def _refund_problem(self, request: RefundRequest, message: str) -> RefundResult:
        return RefundResult(
            success=False,
            status=PaymentStatus.PAID,
            transaction_reference=request.transaction_reference,
            message=message,
        )

    @staticmethod
    def _currency_of(intent: Any) -> str:
        return str(getattr(intent, "currency", "") or "")


def _as_text(value: Any) -> str | None:
    return str(value) if value is not None else None


def _read(source: Any, path: str) -> Any:
    """Follow a dotted path through whatever Stripe returned.

    Stripe hands back objects that answer to attribute access and raise
    ``AttributeError`` for absent keys, while the tests (and Stripe's own
    nested ``metadata``) hand back plain dicts. One reader that treats "absent"
    as ``None`` keeps that difference out of every caller.
    """
    current = source
    for part in path.split("."):
        value = getattr(current, part, None)
        if value is None and isinstance(current, Mapping):
            value = current.get(part)
        if value is None:
            return None
        current = value
    return current


def _reported_amount(obj: Any) -> Any:
    """What Stripe says moved, under whichever name this event carries it.

    A Checkout Session totals ``amount_total``, a settled intent reports
    ``amount_received``, a charge or refund just has ``amount``.
    """
    for key in ("amount_total", "amount_received", "amount", "amount_refunded"):
        value = _read(obj, key)
        if value is not None:
            return value
    return None


def _reference_from(obj: Any) -> str | None:
    """Our reference, from wherever this event kind keeps it.

    ``client_reference_id`` is what a Checkout Session carries; a payment intent
    or charge has only the metadata attached at creation time, and a refund
    created in Stripe's dashboard carries neither, in which case the event is not
    about a payment this shop can identify.
    """
    for path in ("client_reference_id", "metadata.reference", "metadata.payment_reference"):
        value = _read(obj, path)
        if isinstance(value, str) and value:
            return value
    return None


def _failure_message(intent: Any) -> str | None:
    """Stripe's own words for a declined payment, when it bothered to say any."""
    error = getattr(intent, "last_payment_error", None)
    message = getattr(error, "message", None)
    if message is None and isinstance(error, Mapping):
        message = error.get("message")
    return _as_text(message)
