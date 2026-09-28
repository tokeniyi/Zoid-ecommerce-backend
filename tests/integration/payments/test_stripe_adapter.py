"""The Stripe adapter, against a scripted Stripe.

The SDK is never allowed to reach the network: the adapter is handed a double
with the same service paths as ``stripe.StripeClient``. What is proved is that
Stripe's shapes -- Checkout Sessions, minor units, payment-intent statuses, its
refund enum -- never leak past this adapter.

Webhook intake is the one place the real SDK is used, because Stripe's signature
scheme is Stripe's code and not ours: it is pure HMAC over the raw body, so it
can be exercised honestly here without a network or a key.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
import stripe

from app.domains.payments.domain.enums import PaymentAction, PaymentStatus, WebhookKind
from app.domains.payments.domain.gateway import (
    AbstractPaymentGateway,
    PaymentRequest,
    RefundRequest,
)
from app.domains.payments.domain.webhooks import AbstractWebhookAdapter
from app.integrations.payments.stripe import StripePaymentGateway
from app.shared.exceptions import (
    ProviderNotConfiguredError,
    SignatureVerificationError,
    ValidationError,
)

SECRET = "sk_test_stripe"
WEBHOOK_SECRET = "whsec_test_stripe"
RETURN_URL = "http://localhost:5173/checkout"
INTERNAL_REFERENCE = "PAY-INTERNAL1"
SESSION_URL = "https://checkout.stripe.com/c/pay/cs_test_1"


def _request(
    amount: Decimal = Decimal("42000.00"), currency: str = "NGN"
) -> PaymentRequest:
    return PaymentRequest(
        reference=INTERNAL_REFERENCE,
        amount=amount,
        currency=currency,
        email="ada@example.com",
        order_reference="ZD-ORDER1",
    )


def _session(**overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {"id": "cs_test_1", "url": SESSION_URL}
    values.update(overrides)
    return SimpleNamespace(**values)


def _intent(status: str = "succeeded", **overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "id": "pi_test_1",
        "status": status,
        "amount_received": 4200000,
        "currency": "ngn",
        "last_payment_error": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _refund(status: str = "succeeded", **overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "id": "re_test_1",
        "status": status,
        "amount": 4200000,
        "currency": "ngn",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeStripeClient:
    """The three Stripe services the adapter touches, with recorded calls."""

    def __init__(
        self,
        *,
        session: Any = None,
        intents: Any = None,
        refund: Any = None,
        error: Exception | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._error = error
        self._results = {
            "session": session if session is not None else _session(),
            "intents": SimpleNamespace(data=intents if intents is not None else [_intent()]),
            "refund": refund if refund is not None else _refund(),
        }
        self.v1 = SimpleNamespace(
            checkout=SimpleNamespace(
                sessions=self._service("session", "create", "checkout.sessions.create")
            ),
            payment_intents=self._service("intents", "search", "payment_intents.search"),
            refunds=self._service("refund", "create", "refunds.create"),
        )

    def _service(self, key: str, method: str, path: str) -> Any:
        """A Stripe service object: one method, recording what it was asked."""

        def call(**params: Any) -> Any:
            self.calls.append((path, params))
            if self._error is not None:
                raise self._error
            result = self._results[key]
            return result(**params) if callable(result) else result

        return SimpleNamespace(**{method: call})

    def params(self, name: str) -> dict[str, Any]:
        """The keyword arguments of the first call to one Stripe service."""
        return next(params for called, params in self.calls if called == name)

    @property
    def names(self) -> list[str]:
        return [called for called, _ in self.calls]


def _gateway(client: Any | None = None, *, secret_key: str = SECRET) -> StripePaymentGateway:
    return StripePaymentGateway(
        secret_key=secret_key,
        return_url=RETURN_URL,
        client=client if client is not None else FakeStripeClient(),
    )


def _notifier(
    *,
    webhook_secret: str = WEBHOOK_SECRET,
    client: Any | None = None,
) -> StripePaymentGateway:
    """The inbound half. It is handed a recording client so a test can prove that
    reading a notification never makes an API call of its own."""
    return StripePaymentGateway(
        secret_key=SECRET,
        return_url=RETURN_URL,
        webhook_secret=webhook_secret,
        client=client if client is not None else FakeStripeClient(),
    )


def _event(type_name: str, obj: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"id": "evt_test_1", "type": type_name, "data": {"object": obj}}
    body.update(overrides)
    return body


def _intent_object(**overrides: Any) -> dict[str, Any]:
    obj: dict[str, Any] = {
        "id": "pi_test_1",
        "status": "succeeded",
        "amount_received": 4200000,
        "currency": "ngn",
        "metadata": {"reference": INTERNAL_REFERENCE},
    }
    obj.update(overrides)
    return obj


def _session_object(**overrides: Any) -> dict[str, Any]:
    obj: dict[str, Any] = {
        "id": "cs_test_1",
        "amount_total": 4200000,
        "currency": "ngn",
        "client_reference_id": INTERNAL_REFERENCE,
    }
    obj.update(overrides)
    return obj


def _notify(
    body: dict[str, Any] | bytes,
    *,
    secret: str = WEBHOOK_SECRET,
    timestamp: int | None = None,
) -> tuple[bytes, dict[str, str]]:
    """Play Stripe: ``t=<ts>,v1=<hmac of "<ts>.<raw body>">``, as it signs it."""
    payload = body if isinstance(body, bytes) else json.dumps(body).encode()
    stamp = int(time.time()) if timestamp is None else timestamp
    signed = f"{stamp}.{payload.decode()}".encode()
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return payload, {"stripe-signature": f"t={stamp},v1={digest}"}


# --- the contract -------------------------------------------------------------


def test_the_adapter_is_a_payment_gateway() -> None:
    gateway = _gateway()

    assert isinstance(gateway, AbstractPaymentGateway)
    assert gateway.provider == "stripe"


# --- initiation ---------------------------------------------------------------


async def test_initiation_opens_a_checkout_session_in_stripes_shape() -> None:
    client = FakeStripeClient()

    await _gateway(client).create_payment(_request())

    params = client.params("checkout.sessions.create")
    assert params["mode"] == "payment"
    assert params["customer_email"] == "ada@example.com"
    assert params["client_reference_id"] == INTERNAL_REFERENCE
    line = params["line_items"][0]
    assert line["quantity"] == 1
    assert line["price_data"]["unit_amount"] == 4200000  # kobo, Stripe's minor unit
    assert line["price_data"]["currency"] == "ngn"
    assert "ZD-ORDER1" in line["price_data"]["product_data"]["name"]
    assert params["metadata"]["reference"] == INTERNAL_REFERENCE
    assert params["metadata"]["order_reference"] == "ZD-ORDER1"


async def test_the_customer_comes_back_to_our_site_carrying_our_reference() -> None:
    client = FakeStripeClient()

    await _gateway(client).create_payment(_request())

    params = client.params("checkout.sessions.create")
    assert params["success_url"].startswith(RETURN_URL)
    assert f"reference={INTERNAL_REFERENCE}" in params["success_url"]
    assert f"reference={INTERNAL_REFERENCE}" in params["cancel_url"]


async def test_a_stripe_session_url_becomes_a_generic_redirect() -> None:
    initiation = await _gateway(FakeStripeClient()).create_payment(_request())

    assert initiation.success is True
    assert initiation.status is PaymentStatus.PENDING
    assert initiation.transaction_reference == INTERNAL_REFERENCE
    assert initiation.provider_reference == "cs_test_1"
    assert initiation.checkout_url == SESSION_URL
    # The client is told to redirect; which provider is not its business.
    assert initiation.action is PaymentAction.REDIRECT


@pytest.mark.parametrize(
    "currency,expected",
    [("NGN", 4200000), ("JPY", 42000)],
)
async def test_amounts_are_stripest_minor_units(
    currency: str, expected: int
) -> None:
    client = FakeStripeClient()

    await _gateway(client).create_payment(
        _request(amount=Decimal("42000.00"), currency=currency)
    )

    params = client.params("checkout.sessions.create")
    assert params["line_items"][0]["price_data"]["unit_amount"] == expected


async def test_a_session_without_a_url_is_not_reported_as_payable() -> None:
    client = FakeStripeClient(session=_session(url=None))

    initiation = await _gateway(client).create_payment(_request())

    assert initiation.success is False
    assert initiation.status is PaymentStatus.PENDING


async def test_stripe_refusing_the_request_is_a_decline_not_an_exception() -> None:
    client = FakeStripeClient(error=stripe.InvalidRequestError("bad amount", param="amount"))

    initiation = await _gateway(client).create_payment(_request())

    assert initiation.success is False
    assert initiation.status is PaymentStatus.FAILED
    assert initiation.message == "bad amount"


async def test_stripe_being_unreachable_is_not_a_decline() -> None:
    client = FakeStripeClient(error=stripe.APIConnectionError("connection reset"))

    initiation = await _gateway(client).create_payment(_request())

    assert initiation.success is False
    assert initiation.status is PaymentStatus.PENDING
    assert "reach" in (initiation.message or "").lower()


# --- verification -------------------------------------------------------------


async def test_verification_finds_the_payment_by_our_own_reference() -> None:
    client = FakeStripeClient()

    await _gateway(client).verify_payment(INTERNAL_REFERENCE)

    params = client.params("payment_intents.search")
    assert params["query"] == f"metadata['reference']:'{INTERNAL_REFERENCE}'"
    assert params["limit"] == 1


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("succeeded", PaymentStatus.PAID),
        ("requires_payment_method", PaymentStatus.FAILED),
        ("canceled", PaymentStatus.FAILED),
        ("processing", PaymentStatus.PENDING),
        ("requires_action", PaymentStatus.PENDING),
        ("whichever_status_stripe_invents_next", PaymentStatus.PENDING),
    ],
)
async def test_a_stripe_intent_status_is_normalised(
    status: str, expected: PaymentStatus
) -> None:
    client = FakeStripeClient(intents=[_intent(status)])

    verification = await _gateway(client).verify_payment(INTERNAL_REFERENCE)

    assert verification.success is True  # Stripe answered
    assert verification.status is expected  # ...with this verdict


async def test_verification_reports_the_money_that_actually_arrived() -> None:
    verification = await _gateway(FakeStripeClient()).verify_payment(INTERNAL_REFERENCE)

    assert verification.amount == Decimal("42000.00")  # back from kobo
    assert verification.provider_reference == "pi_test_1"
    assert verification.transaction_reference == INTERNAL_REFERENCE


async def test_a_declined_intent_says_why() -> None:
    client = FakeStripeClient(
        intents=[
            _intent(
                "requires_payment_method",
                last_payment_error=SimpleNamespace(message="Your card was declined."),
            )
        ]
    )

    verification = await _gateway(client).verify_payment(INTERNAL_REFERENCE)

    assert verification.status is PaymentStatus.FAILED
    assert verification.message == "Your card was declined."


async def test_nothing_at_stripe_yet_is_still_an_open_attempt() -> None:
    """The customer may never have finished the hosted checkout: no verdict."""
    client = FakeStripeClient(intents=[])

    verification = await _gateway(client).verify_payment(INTERNAL_REFERENCE)

    assert verification.success is True
    assert verification.status is PaymentStatus.PENDING
    assert "yet" in (verification.message or "").lower()


async def test_a_payment_the_browser_claims_is_not_taken_on_trust() -> None:
    """Stripe is asked; the answer, not the request, settles the transaction."""
    client = FakeStripeClient(intents=[_intent("requires_payment_method")])

    verification = await _gateway(client).verify_payment(INTERNAL_REFERENCE)

    assert verification.status is not PaymentStatus.PAID


# --- refunds ------------------------------------------------------------------


async def test_a_refund_is_aimed_at_the_intent_behind_our_reference() -> None:
    client = FakeStripeClient()

    result = await _gateway(client).refund_payment(
        RefundRequest(transaction_reference=INTERNAL_REFERENCE)
    )

    assert client.names == ["payment_intents.search", "refunds.create"]
    params = client.params("refunds.create")
    assert params["payment_intent"] == "pi_test_1"
    assert "amount" not in params  # absent means "all of it" to Stripe
    assert result.success is True
    assert result.status is PaymentStatus.REFUNDED
    assert result.provider_refund_reference == "re_test_1"


async def test_a_partial_refund_is_refunded_in_minor_units() -> None:
    client = FakeStripeClient()

    await _gateway(client).refund_payment(
        RefundRequest(transaction_reference=INTERNAL_REFERENCE, amount=Decimal("1000.00"))
    )

    assert client.params("refunds.create")["amount"] == 100000


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("duplicate", {"reason": "duplicate"}),
        ("Requested by customer", {"reason": "requested_by_customer"}),
        ("One jersey returned", {"metadata": {"reason": "One jersey returned"}}),
    ],
)
async def test_stripes_refund_reason_enum_is_not_treated_as_suggestion_box(
    reason: str, expected: dict[str, Any]
) -> None:
    client = FakeStripeClient()

    await _gateway(client).refund_payment(
        RefundRequest(transaction_reference=INTERNAL_REFERENCE, reason=reason)
    )

    params = client.params("refunds.create")
    for key, value in expected.items():
        assert params[key] == value


@pytest.mark.parametrize(
    ("status", "message"),
    [("pending", "pending"), ("failed", "failed")],
)
async def test_an_unfinished_refund_leaves_the_payment_paid(
    status: str, message: str
) -> None:
    client = FakeStripeClient(refund=_refund(status))

    result = await _gateway(client).refund_payment(
        RefundRequest(transaction_reference=INTERNAL_REFERENCE)
    )

    assert result.success is False
    assert result.status is PaymentStatus.PAID
    assert message in (result.message or "")


async def test_a_refund_with_nothing_to_refund_says_so() -> None:
    client = FakeStripeClient(intents=[])

    result = await _gateway(client).refund_payment(
        RefundRequest(transaction_reference=INTERNAL_REFERENCE)
    )

    assert result.success is False
    assert result.status is PaymentStatus.PAID
    assert "refunds.create" not in client.names


async def test_stripe_being_unreachable_does_not_refund_anything() -> None:
    client = FakeStripeClient(error=stripe.APIConnectionError("connection reset"))

    result = await _gateway(client).refund_payment(
        RefundRequest(transaction_reference=INTERNAL_REFERENCE)
    )

    assert result.success is False
    assert result.status is PaymentStatus.PAID


# --- webhook intake -----------------------------------------------------------


def test_the_same_adapter_reads_stripes_notifications() -> None:
    assert isinstance(_notifier(), AbstractWebhookAdapter)


def test_a_signed_event_becomes_business_vocabulary() -> None:
    client = FakeStripeClient()
    payload, headers = _notify(_event("payment_intent.succeeded", _intent_object()))

    notification = _notifier(client=client).parse_notification(
        payload=payload, headers=headers
    )

    assert notification.provider == "stripe"
    assert notification.kind is WebhookKind.PAYMENT_PAID
    assert notification.event_id == "evt_test_1"
    assert notification.reference == INTERNAL_REFERENCE
    assert notification.provider_reference == "pi_test_1"
    assert notification.amount == Decimal("42000.00")  # out of Stripe's minor units
    # News arrives; the adapter does not go and ask about it, so no API call here.
    assert client.names == []


@pytest.mark.parametrize(
    ("type_name", "obj", "expected"),
    [
        ("checkout.session.completed", _session_object(), WebhookKind.PAYMENT_PAID),
        ("payment_intent.succeeded", _intent_object(), WebhookKind.PAYMENT_PAID),
        (
            "charge.succeeded",
            {"id": "ch_1", "amount": 4200000, "currency": "ngn"},
            WebhookKind.PAYMENT_PAID,
        ),
        (
            "checkout.session.expired",
            _session_object(status="expired"),
            WebhookKind.PAYMENT_FAILED,
        ),
        (
            "payment_intent.payment_failed",
            _intent_object(status="requires_payment_method"),
            WebhookKind.PAYMENT_FAILED,
        ),
        (
            "charge.dispute.created",
            {"id": "dp_1", "charge": "ch_1"},
            WebhookKind.PAYMENT_FAILED,
        ),
        (
            "charge.refunded",
            {"id": "ch_1", "amount": 4200000, "amount_refunded": 4200000},
            WebhookKind.REFUND_SETTLED,
        ),
        ("customer.created", {"id": "cus_1"}, WebhookKind.IGNORED),
        ("issuing_authorization.request", {"id": "ia_1"}, WebhookKind.IGNORED),
    ],
)
def test_stripes_event_types_are_translated(
    type_name: str, obj: dict[str, Any], expected: WebhookKind
) -> None:
    payload, headers = _notify(_event(type_name, obj))

    notification = _notifier().parse_notification(payload=payload, headers=headers)

    assert notification.kind is expected
    assert notification.event_id == "evt_test_1"  # even news we ignore is traceable


@pytest.mark.parametrize(
    ("type_name", "obj"),
    [
        ("checkout.session.completed", _session_object()),
        ("payment_intent.succeeded", _intent_object()),
    ],
    ids=("checkout-session", "payment-intent"),
)
def test_our_reference_is_found_wherever_this_event_kind_keeps_it(
    type_name: str, obj: dict[str, Any]
) -> None:
    payload, headers = _notify(_event(type_name, obj))

    notification = _notifier().parse_notification(payload=payload, headers=headers)

    assert notification.names_our_payment is True
    assert notification.reference == INTERNAL_REFERENCE


def test_a_refund_made_in_stripes_dashboard_names_no_payment_of_ours() -> None:
    """It is authentic and it is news; which transaction it belongs to is another
    question, and the adapter does not guess at an answer."""
    payload, headers = _notify(
        _event("refund.created", {"id": "re_test_9", "amount": 500000})
    )

    notification = _notifier().parse_notification(payload=payload, headers=headers)

    assert notification.kind is WebhookKind.REFUND_SETTLED
    assert notification.names_our_payment is False


def test_a_declined_payment_says_why_in_stripes_words() -> None:
    event = _event(
        "payment_intent.payment_failed",
        _intent_object(
            status="requires_payment_method",
            amount_received=None,
            last_payment_error={"message": "Your card was declined."},
        ),
    )
    payload, headers = _notify(event)

    notification = _notifier().parse_notification(payload=payload, headers=headers)

    assert notification.message == "Your card was declined."
    assert notification.amount is None


def test_the_signature_covers_the_bytes_sent_not_a_re_encoded_copy() -> None:
    raw = (
        b'{"data":{"object":{"metadata":{"reference":"PAY-INTERNAL1"},'
        b'"amount_received":4200000,"currency":"ngn","id":"pi_test_1"}},'
        b'"type":"payment_intent.succeeded","id":"evt_test_1"}'
    )
    payload, headers = _notify(raw)

    notification = _notifier().parse_notification(payload=payload, headers=headers)

    assert notification.reference == INTERNAL_REFERENCE
    assert notification.amount == Decimal("42000.00")


@pytest.mark.parametrize(
    "forged",
    [
        pytest.param("wrong_secret", id="signed-by-somebody-else"),
        pytest.param("missing_header", id="no-signature-header"),
        pytest.param("empty_header", id="empty-signature-header"),
        pytest.param("stale", id="signature-outside-the-tolerance-window"),
        pytest.param("tampered_body", id="valid-signature-over-a-different-body"),
    ],
)
def test_a_payload_that_is_not_authentically_stripes_is_not_read(forged: str) -> None:
    body = _event("payment_intent.succeeded", _intent_object())
    payload, headers = _notify(body)
    if forged == "tampered_body":
        less = _event("payment_intent.succeeded", _intent_object(amount_received=100))
        payload = json.dumps(less).encode()
    elif forged == "stale":
        payload, headers = _notify(body, timestamp=int(time.time()) - 3600)
    elif forged == "wrong_secret":
        _, headers = _notify(body, secret="whsec_not_stripe")
    elif forged == "missing_header":
        headers = {}
    else:
        headers = {"stripe-signature": ""}

    with pytest.raises(SignatureVerificationError):
        _notifier().parse_notification(payload=payload, headers=headers)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"not json at all", id="unreadable"),
        pytest.param({"type": "charge.succeeded"}, id="no-event-id"),
    ],
)
def test_authentic_nonsense_is_a_bad_request_not_a_crash(body: bytes | dict) -> None:
    payload, headers = _notify(body)

    with pytest.raises(ValidationError):
        _notifier().parse_notification(payload=payload, headers=headers)


def test_notifications_cannot_be_read_without_a_signing_secret() -> None:
    payload, headers = _notify(_event("payment_intent.succeeded", _intent_object()))

    with pytest.raises(ProviderNotConfiguredError):
        _notifier(webhook_secret="").parse_notification(payload=payload, headers=headers)


# --- configuration -----------------------------------------------------------


@pytest.mark.parametrize("capability", ["create", "verify", "refund"])
async def test_missing_credentials_refuse_to_charge_anything(capability: str) -> None:
    """Without a key the adapter never even builds an SDK client."""
    gateway = StripePaymentGateway(secret_key="", return_url=RETURN_URL)
    call = {
        "create": lambda: gateway.create_payment(_request()),
        "verify": lambda: gateway.verify_payment(INTERNAL_REFERENCE),
        "refund": lambda: gateway.refund_payment(
            RefundRequest(transaction_reference=INTERNAL_REFERENCE)
        ),
    }[capability]

    with pytest.raises(ProviderNotConfiguredError):
        await call()
