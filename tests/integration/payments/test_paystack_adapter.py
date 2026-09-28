"""The Paystack adapter, against a scripted Paystack.

No network, no real keys: the adapter's transport is a replay of recorded
provider answers. What is being proved is the translation in both directions --
our contract in, Paystack's wire format out, and Paystack's envelope back into
normalised results.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import httpx
import pytest

from app.domains.payments.domain.enums import PaymentAction, PaymentStatus, WebhookKind
from app.domains.payments.domain.gateway import (
    AbstractPaymentGateway,
    PaymentRequest,
    RefundRequest,
)
from app.domains.payments.domain.webhooks import AbstractWebhookAdapter
from app.integrations.payments.paystack import PaystackPaymentGateway
from app.shared.exceptions import (
    ProviderNotConfiguredError,
    SignatureVerificationError,
    ValidationError,
)

SECRET = "sk_test_paystack"
WEBHOOK_SECRET = "whsec_test_paystack"
CALLBACK = "http://localhost:5173/checkout"
INTERNAL_REFERENCE = "PAY-INTERNAL1"


def _request(amount: Decimal = Decimal("42000.00")) -> PaymentRequest:
    return PaymentRequest(
        reference=INTERNAL_REFERENCE,
        amount=amount,
        currency="NGN",
        email="ada@example.com",
        order_reference="ZD-ORDER1",
    )


def _initialized(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "authorization_url": "https://checkout.paystack.com/0123456789abcdef",
        "access_code": "0123456789abcdef",
        "reference": INTERNAL_REFERENCE,
    }
    data.update(overrides)
    return {"status": True, "message": "Authorization URL created", "data": data}


def _verified(status: str, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "status": status,
        "reference": INTERNAL_REFERENCE,
        "gateway_reference": "PS-GW-999",
        "amount": 4200000,
        "currency": "NGN",
    }
    data.update(overrides)
    return {"status": True, "message": "Transaction verified successfully", "data": data}


class PaystackRecorder:
    """A fake Paystack: replies in order, and remembers what it was asked."""

    def __init__(
        self,
        *replies: tuple[int, dict[str, Any]],
        error: Exception | None = None,
    ) -> None:
        self.error = error
        self.requests: list[httpx.Request] = []
        self._replies: Iterator[tuple[int, dict[str, Any]]] = iter(replies)
        self._last: tuple[int, dict[str, Any]] = (200, _initialized())

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        try:
            self._last = next(self._replies)
        except StopIteration:
            pass
        status_code, body = self._last
        return httpx.Response(status_code, json=body)

    def body(self, index: int = 0) -> dict[str, Any]:
        raw = self.requests[index].content
        return json.loads(raw.decode()) if raw else {}


def _gateway(recorder: PaystackRecorder, *, secret_key: str = SECRET) -> PaystackPaymentGateway:
    return PaystackPaymentGateway(
        secret_key=secret_key,
        callback_url=CALLBACK,
        transport=recorder.transport,
    )


def _notifier(*, webhook_secret: str = WEBHOOK_SECRET) -> PaystackPaymentGateway:
    """An adapter for the inbound direction: it needs no transport, it talks to
    nobody, it only decides whether a payload is authentically Paystack's."""
    return PaystackPaymentGateway(
        secret_key=SECRET,
        callback_url=CALLBACK,
        webhook_secret=webhook_secret,
    )


def _event(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "event": "charge.success",
        "data": {
            "id": 500,
            "status": "success",
            "reference": INTERNAL_REFERENCE,
            "amount": 4200000,
            "currency": "NGN",
            "gateway_reference": "PS-GW-999",
        },
    }
    body.update(overrides)
    return body


def _notify(
    body: dict[str, Any] | bytes, *, secret: str = WEBHOOK_SECRET
) -> tuple[bytes, dict[str, str]]:
    """Play Paystack: sign the exact bytes a notification would be sent as."""
    payload = body if isinstance(body, bytes) else json.dumps(body).encode()
    signature = hmac.new(secret.encode(), payload, hashlib.sha512).hexdigest()
    return payload, {"paystack-signature": signature}


# --- the contract -------------------------------------------------------------


def test_the_adapter_is_a_payment_gateway() -> None:
    gateway = _gateway(PaystackRecorder())

    assert isinstance(gateway, AbstractPaymentGateway)
    assert gateway.provider == "paystack"


# --- initiation ---------------------------------------------------------------


async def test_initiation_asks_paystack_in_paystacks_shape() -> None:
    recorder = PaystackRecorder((200, _initialized()))

    await _gateway(recorder).create_payment(_request())

    request = recorder.requests[0]
    assert request.method == "POST"
    assert request.url.path == "/transaction/initialize"
    assert request.headers["Authorization"] == f"Bearer {SECRET}"
    body = recorder.body()
    assert body["email"] == "ada@example.com"
    assert body["currency"] == "NGN"
    assert body["reference"] == INTERNAL_REFERENCE  # our reference, not theirs
    assert body["amount"] == 4200000  # kobo, because Paystack only speaks kobo
    assert body["callback_url"] == CALLBACK
    custom = body["metadata"]["custom_fields"][0]
    assert custom["value"] == "ZD-ORDER1"


async def test_a_paystack_authorization_url_becomes_a_generic_redirect() -> None:
    recorder = PaystackRecorder((200, _initialized()))

    initiation = await _gateway(recorder).create_payment(_request())

    assert initiation.success is True
    assert initiation.status is PaymentStatus.PENDING
    assert initiation.transaction_reference == INTERNAL_REFERENCE
    assert initiation.provider_reference == "0123456789abcdef"
    assert initiation.checkout_url == "https://checkout.paystack.com/0123456789abcdef"
    assert initiation.action is PaymentAction.REDIRECT
    assert initiation.next_action == (
        PaymentAction.REDIRECT,
        "https://checkout.paystack.com/0123456789abcdef",
    )


@pytest.mark.parametrize(
    ("status_code", "message"),
    [(200, "Invalid API Key"), (400, "Amount must be given in kobo")],
)
async def test_paystack_saying_no_is_a_decline_not_an_exception(
    status_code: int, message: str
) -> None:
    recorder = PaystackRecorder(
        (status_code, {"status": False, "message": message, "data": None})
    )

    initiation = await _gateway(recorder).create_payment(_request())

    assert initiation.success is False
    assert initiation.status is PaymentStatus.FAILED
    assert initiation.message == message


async def test_a_redirect_without_a_page_is_not_reported_as_payable() -> None:
    recorder = PaystackRecorder((200, _initialized(authorization_url="")))

    initiation = await _gateway(recorder).create_payment(_request())

    assert initiation.success is False
    assert initiation.status is PaymentStatus.FAILED


@pytest.mark.parametrize(
    "error",
    [httpx.ConnectError("connection refused"), httpx.ReadTimeout("read timed out")],
)
async def test_paystack_being_unreachable_is_not_a_decline(error: Exception) -> None:
    recorder = PaystackRecorder(error=error)

    initiation = await _gateway(recorder).create_payment(_request())

    # Unsettled, so the next attempt reopens the conversation.
    assert initiation.success is False
    assert initiation.status is PaymentStatus.PENDING
    assert "reach" in (initiation.message or "").lower()


# --- verification -------------------------------------------------------------


async def test_verification_asks_paystack_about_our_reference() -> None:
    recorder = PaystackRecorder((200, _verified("success")))

    await _gateway(recorder).verify_payment(INTERNAL_REFERENCE)

    assert recorder.requests[0].method == "GET"
    assert recorder.requests[0].url.path == f"/transaction/verify/{INTERNAL_REFERENCE}"


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("success", PaymentStatus.PAID),
        ("failed", PaymentStatus.FAILED),
        ("pending", PaymentStatus.PENDING),
        ("abandoned", PaymentStatus.PENDING),  # unknown is never a verdict
    ],
)
async def test_paystacks_transaction_status_is_normalised(
    answer: str, expected: PaymentStatus
) -> None:
    recorder = PaystackRecorder((200, _verified(answer)))

    verification = await _gateway(recorder).verify_payment(INTERNAL_REFERENCE)

    assert verification.success is True  # Paystack answered
    assert verification.status is expected  # ...and this is where the money is


async def test_verification_reports_the_money_that_actually_arrived() -> None:
    recorder = PaystackRecorder((200, _verified("success")))

    verification = await _gateway(recorder).verify_payment(INTERNAL_REFERENCE)

    assert verification.amount == Decimal("42000.00")  # back from kobo
    assert verification.provider_reference == "PS-GW-999"
    assert verification.transaction_reference == INTERNAL_REFERENCE


async def test_verification_cannot_invent_a_settled_payment() -> None:
    """A 404 from Paystack is 'no answer', never a paid status."""
    recorder = PaystackRecorder(
        (404, {"status": False, "message": "No such transaction", "data": None})
    )

    verification = await _gateway(recorder).verify_payment(INTERNAL_REFERENCE)

    assert verification.success is False
    assert verification.status is PaymentStatus.PENDING


async def test_verification_when_paystack_cannot_be_reached() -> None:
    recorder = PaystackRecorder(error=httpx.ConnectError("connection refused"))

    verification = await _gateway(recorder).verify_payment(INTERNAL_REFERENCE)

    assert verification.success is False
    assert verification.status is PaymentStatus.PENDING


# --- refunds ------------------------------------------------------------------


async def test_a_full_refund_is_requested_without_an_amount() -> None:
    recorder = PaystackRecorder(
        (200, {"status": True, "message": "Refund has been queued", "data": {"id": 91}})
    )

    result = await _gateway(recorder).refund_payment(
        RefundRequest(transaction_reference=INTERNAL_REFERENCE)
    )

    assert recorder.requests[0].url.path == f"/transaction/{INTERNAL_REFERENCE}/refund"
    assert "amount" not in recorder.body()
    assert result.success is True
    assert result.status is PaymentStatus.REFUNDED
    assert result.provider_refund_reference == "91"


async def test_a_partial_refund_carries_kobo_and_the_merchants_note() -> None:
    recorder = PaystackRecorder(
        (200, {"status": True, "message": "Refund has been queued", "data": {"id": 92}})
    )

    await _gateway(recorder).refund_payment(
        RefundRequest(
            transaction_reference=INTERNAL_REFERENCE,
            amount=Decimal("1000.00"),
            reason="One jersey returned",
        )
    )

    body = recorder.body()
    assert body["amount"] == 100000
    assert body["merchant_note"] == "One jersey returned"


@pytest.mark.parametrize(
    "reply",
    [
        (400, {"status": False, "message": "Refund amount exceeds available balance"}),
        (
            200,
            {
                "status": True,
                "message": "Refund failed",
                "data": {"id": 93, "status": "failed"},
            },
        ),
    ],
)
async def test_a_refused_refund_leaves_the_payment_paid(reply: tuple[int, Any]) -> None:
    recorder = PaystackRecorder(reply)

    result = await _gateway(recorder).refund_payment(
        RefundRequest(transaction_reference=INTERNAL_REFERENCE)
    )

    assert result.success is False
    assert result.status is PaymentStatus.PAID
    assert result.message


# --- webhook intake -----------------------------------------------------------


def test_the_same_adapter_reads_paystacks_notifications() -> None:
    """One class owns both directions, so a webhook can never be handled by an
    implementation that has not been given a signature scheme."""
    assert isinstance(_notifier(), AbstractWebhookAdapter)


def test_a_signed_event_becomes_business_vocabulary() -> None:
    payload, headers = _notify(_event())

    notification = _notifier().parse_notification(payload=payload, headers=headers)

    assert notification.provider == "paystack"
    assert notification.kind is WebhookKind.PAYMENT_PAID
    assert notification.reference == INTERNAL_REFERENCE  # our reference back again
    assert notification.event_id == "charge.success:500"
    assert notification.amount == Decimal("42000.00")  # out of kobo
    assert notification.currency == "NGN"
    assert notification.provider_reference == "PS-GW-999"


@pytest.mark.parametrize(
    "body",
    [
        {"event": "charge.success", "data": {"id": 500}},
        {
            "event": {"id": 12, "description": "charge.success"},
            "data": {"id": 500},
        },
    ],
    ids=("event-as-a-name", "event-as-an-object"),
)
def test_both_ways_paystack_spells_an_event_are_read_the_same_way(body: dict) -> None:
    payload, headers = _notify(body)

    notification = _notifier().parse_notification(payload=payload, headers=headers)

    assert notification.kind is WebhookKind.PAYMENT_PAID
    assert notification.event_id  # redeliveries must be recognisable


def test_the_same_event_twice_carries_the_same_id() -> None:
    """The idempotency key has to be stable across a redelivery, or it is nothing."""
    payload, headers = _notify(_event())
    gateway = _notifier()

    first = gateway.parse_notification(payload=payload, headers=headers)
    second = gateway.parse_notification(payload=payload, headers=headers)

    assert first == second


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("charge.success", WebhookKind.PAYMENT_PAID),
        ("payment.success", WebhookKind.PAYMENT_PAID),
        ("charge.failed", WebhookKind.PAYMENT_FAILED),
        ("payment.failed", WebhookKind.PAYMENT_FAILED),
        ("charge.reversed", WebhookKind.PAYMENT_FAILED),
        ("refund.successful", WebhookKind.REFUND_SETTLED),
        ("refund.failed", WebhookKind.IGNORED),
        ("subscription.create", WebhookKind.IGNORED),  # unlisted is recorded, not acted on
        ("SOME BRAND NEW EVENT", WebhookKind.IGNORED),
    ],
)
def test_paystacks_event_names_are_translated(name: str, expected: WebhookKind) -> None:
    payload, headers = _notify(_event(event=name))

    assert _notifier().parse_notification(payload=payload, headers=headers).kind is expected


def test_a_failure_event_carries_paystacks_reason() -> None:
    event = _event(
        event="charge.failed",
        data={
            "id": 501,
            "status": "failed",
            "reference": INTERNAL_REFERENCE,
            "failure_reason": "insufficient funds",
        },
    )
    payload, headers = _notify(event)

    notification = _notifier().parse_notification(payload=payload, headers=headers)

    assert notification.message == "insufficient funds"
    assert notification.amount is None


def test_a_refund_event_reads_the_reference_one_level_down() -> None:
    """A refund event describes a refund, and hangs the transaction inside it."""
    event = _event(
        event="refund.successful",
        data={
            "id": 900,
            "transaction": {"id": 500, "reference": INTERNAL_REFERENCE},
        },
    )
    payload, headers = _notify(event)

    notification = _notifier().parse_notification(payload=payload, headers=headers)

    assert notification.kind is WebhookKind.REFUND_SETTLED
    assert notification.reference == INTERNAL_REFERENCE


def test_the_signature_is_over_the_bytes_sent_not_a_re_encoded_copy() -> None:
    """Keys in Paystack's order, spacing of Paystack's choosing: still authentic.

    Anything that parsed the body and re-serialised it on the way to verification
    would break this notification, and an honest event would be rejected.
    """
    raw = (
        b'{"data":  {"id":500,"reference":"PAY-INTERNAL1","amount":4200000,'
        b'"currency":"NGN","status":"success"},  "event":"charge.success"}'
    )
    payload, headers = _notify(raw)

    notification = _notifier().parse_notification(payload=payload, headers=headers)

    assert notification.reference == INTERNAL_REFERENCE
    assert notification.amount == Decimal("42000.00")


@pytest.mark.parametrize(
    "tampered",
    [
        pytest.param("different_secret", id="signed-by-somebody-else"),
        pytest.param("missing", id="no-signature-header"),
        pytest.param("empty", id="empty-signature-header"),
    ],
)
def test_a_payload_that_is_not_authentically_paystacks_is_not_read(tampered: str) -> None:
    body = _event()
    payload, _ = _notify(body)
    headers = {
        "different_secret": _notify(body, secret="whsec_something_else")[1],
        "missing": {},
        "empty": {"paystack-signature": ""},
    }[tampered]

    with pytest.raises(SignatureVerificationError):
        _notifier().parse_notification(payload=payload, headers=headers)


def test_a_signed_event_for_a_changed_body_is_refused() -> None:
    """A valid signature over one body must not carry a different body."""
    _, headers = _notify(_event())
    forged = json.dumps(_event(data={"id": 500, "amount": 100})).encode()

    with pytest.raises(SignatureVerificationError):
        _notifier().parse_notification(payload=forged, headers=headers)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"not json at all", id="unreadable"),
        pytest.param(b"[]", id="not-an-object"),
        pytest.param({"data": {"id": 500}}, id="no-event-name"),
        pytest.param({"event": "charge.success", "data": {}}, id="no-event-id"),
    ],
)
def test_authentic_nonsense_is_a_bad_request_not_a_crash(body: bytes | dict) -> None:
    """Verified as sent by Paystack, and still something this shop cannot act on."""
    payload, headers = _notify(body)

    with pytest.raises(ValidationError):
        _notifier().parse_notification(payload=payload, headers=headers)


def test_notifications_cannot_be_read_without_a_signing_secret() -> None:
    """No secret means no way to tell a real event from a forged one, so the
    adapter refuses rather than defaulting to belief."""
    payload, headers = _notify(_event())

    with pytest.raises(ProviderNotConfiguredError):
        _notifier(webhook_secret="").parse_notification(payload=payload, headers=headers)


# --- configuration -----------------------------------------------------------


@pytest.mark.parametrize("capability", ["create", "verify", "refund"])
async def test_missing_credentials_refuse_to_charge_anything(capability: str) -> None:
    recorder = PaystackRecorder((200, _initialized()))
    gateway = _gateway(recorder, secret_key="")
    call = {
        "create": lambda: gateway.create_payment(_request()),
        "verify": lambda: gateway.verify_payment(INTERNAL_REFERENCE),
        "refund": lambda: gateway.refund_payment(
            RefundRequest(transaction_reference=INTERNAL_REFERENCE)
        ),
    }[capability]

    with pytest.raises(ProviderNotConfiguredError):
        await call()

    assert recorder.requests == []
