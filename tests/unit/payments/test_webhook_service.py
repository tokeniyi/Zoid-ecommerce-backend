"""Webhook intake: one notification, one effect, no matter how often it arrives.

The PASS condition this file exists to defend is that repeated identical provider
events cause no duplicate business effects. Every test here therefore asks the
same question in a different situation: *what changed the second time?*

The gateway and the webhook adapter are both doubles; the state machine, the
cascade to the order and the idempotency ledger are the real application code.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

import pytest

from app.domains.orders.domain.entities import Order, OrderItem
from app.domains.orders.domain.enums import OrderStatus
from app.domains.payments.application.notifications import PaidOrderNotifier
from app.domains.payments.application.service import PaymentService
from app.domains.payments.domain.entities import Transaction, WebhookEvent
from app.domains.payments.domain.enums import PaymentStatus, WebhookKind
from app.domains.payments.domain.webhooks import (
    AbstractWebhookAdapter,
    WebhookNotification,
)
from app.shared.exceptions import (
    NotFoundError,
    ProviderNotConfiguredError,
    SignatureVerificationError,
)
from tests.unit.payments.test_order_notification import OWNER, RecordingSender
from tests.unit.payments.test_payment_service import (
    AMOUNT,
    USER_ID,
    FakeGateway,
    InMemoryOrderRepository,
    InMemoryRefundRepository,
    InMemoryTransactionRepository,
    InMemoryWebhookEventRepository,
)

PROVIDER = "fake"
PAYLOAD = b'{"event": "charge.success"}'


class FakeWebhook(AbstractWebhookAdapter):
    """A provider double for the inbound direction.

    It hands over whatever the test tells it to -- including the exception it is
    supposed to raise when the signature does not match, because the application's
    job starts after authentication, not before.
    """

    provider = PROVIDER

    def __init__(self, notification: WebhookNotification | None = None) -> None:
        self.notification = notification
        self.refuses: Exception | None = None
        self.calls: list[tuple[bytes, dict[str, str]]] = []

    def parse_notification(
        self, *, payload: bytes, headers: Mapping[str, str]
    ) -> WebhookNotification:
        self.calls.append((payload, dict(headers)))
        if self.refuses is not None:
            raise self.refuses
        assert self.notification is not None, "test forgot to say what happened"
        return self.notification


def _notification(**overrides: object) -> WebhookNotification:
    fields: dict[str, object] = {
        "provider": PROVIDER,
        "event_id": "evt-1",
        "kind": WebhookKind.PAYMENT_PAID,
        "amount": AMOUNT,
        "currency": "NGN",
        "provider_reference": "prov-1",
    }
    fields.update(overrides)
    return WebhookNotification(**fields)  # type: ignore[arg-type]


@dataclass
class Harness:
    """Everything a webhook test needs to look at afterwards."""

    service: PaymentService
    order: Order
    transaction: Transaction
    orders: InMemoryOrderRepository
    transactions: InMemoryTransactionRepository
    events: InMemoryWebhookEventRepository
    webhook: FakeWebhook
    emails: RecordingSender

    async def receive(
        self,
        *,
        provider: str = PROVIDER,
        payload: bytes = PAYLOAD,
        headers: Mapping[str, str] | None = None,
    ) -> tuple[WebhookEvent, object]:
        return await self.service.handle_webhook(
            provider=provider, payload=payload, headers=headers or {}
        )  # type: ignore[return-value]


async def _harness(
    *, kind: WebhookKind = WebhookKind.PAYMENT_PAID, **notification: object
) -> Harness:
    """A real pending payment, waiting for news about it."""
    order = Order(
        id=10,
        reference="ZD-ABC12345",
        user_id=USER_ID,
        currency="NGN",
        contact_name="Ada Zoid",
        contact_email="ada@example.com",
        contact_phone="+234 800 000 0000",
        address_line="12 Concrete Road",
        city_state="Lagos State",
        items=[
            OrderItem(
                id=1,
                variant_id=11,
                product_slug="alpha",
                product_name="Alpha Jersey",
                size="M",
                quantity=2,
                unit_price=Decimal("21000.00"),
            )
        ],
    )
    transactions = InMemoryTransactionRepository()
    orders = InMemoryOrderRepository(order)
    events = InMemoryWebhookEventRepository()
    webhook = FakeWebhook()
    emails = RecordingSender()
    service = PaymentService(
        transactions=transactions,
        orders=orders,
        refunds=InMemoryRefundRepository(),
        webhook_events=events,
        gateway=FakeGateway(),
        webhook=webhook,
        notifier=PaidOrderNotifier(sender=emails, owner_email=OWNER),
    )
    transaction, _ = await service.initiate(user_id=USER_ID, order_id=10)
    # The event is about this payment unless the test names another one.
    fields: dict[str, object] = {"reference": transaction.reference, **notification}
    webhook.notification = _notification(kind=kind, **fields)
    return Harness(
        service=service,
        order=order,
        transaction=transaction,
        orders=orders,
        transactions=transactions,
        events=events,
        webhook=webhook,
        emails=emails,
    )


# --- a genuine notification ---------------------------------------------------


async def test_a_signed_event_pays_for_the_order_it_names() -> None:
    harness = await _harness()

    receipt, outcome = await harness.receive()

    assert harness.transaction.status is PaymentStatus.PAID
    assert harness.order.status is OrderStatus.PAID
    assert outcome.value == "applied"
    assert receipt.processed is True
    assert receipt.transaction_id == harness.transaction.id
    # The raw bytes and headers are handed to the adapter untouched: the signature
    # is over what the provider sent, not what the framework re-encoded.
    assert harness.webhook.calls == [(PAYLOAD, {})]


async def test_the_event_is_recorded_even_when_it_names_nothing_of_ours() -> None:
    harness = await _harness(reference="PAY-somebody-elses")

    receipt, outcome = await harness.receive()

    assert outcome.value == "unmatched"
    assert receipt.processed is False
    assert harness.transaction.status is PaymentStatus.PENDING
    assert harness.order.status is OrderStatus.PENDING_PAYMENT


async def test_an_event_with_no_business_meaning_is_received_and_left_alone() -> None:
    harness = await _harness(kind=WebhookKind.IGNORED)

    receipt, outcome = await harness.receive()

    assert outcome.value == "ignored"
    assert receipt.kind is WebhookKind.IGNORED
    assert harness.transaction.status is PaymentStatus.PENDING


async def test_a_refund_notification_does_not_re_settle_anything() -> None:
    """Refunds are ledgered when we ask for them; the provider agreeing is not news."""
    harness = await _harness(kind=WebhookKind.REFUND_SETTLED)

    _, outcome = await harness.receive()

    assert outcome.value == "ignored"
    assert harness.transaction.status is PaymentStatus.PENDING


async def test_a_failure_event_fails_the_payment_but_not_the_order() -> None:
    harness = await _harness(
        kind=WebhookKind.PAYMENT_FAILED, message="Card declined", amount=None
    )

    await harness.receive()

    assert harness.transaction.status is PaymentStatus.FAILED
    assert harness.transaction.failure_reason == "Card declined"
    # The customer may try again, so the order keeps waiting for payment.
    assert harness.order.status is OrderStatus.PENDING_PAYMENT


# --- an event nobody sent -----------------------------------------------------


async def test_an_unverifiable_payload_is_not_recorded_as_ever_arriving() -> None:
    harness = await _harness()
    harness.webhook.refuses = SignatureVerificationError("nope")

    with pytest.raises(SignatureVerificationError):
        await harness.receive()

    assert await harness.events.get_by_provider_and_event_id(PROVIDER, "evt-1") is None
    assert harness.transaction.status is PaymentStatus.PENDING
    assert harness.order.status is OrderStatus.PENDING_PAYMENT


async def test_a_notification_for_another_provider_is_not_ours_to_read() -> None:
    harness = await _harness()

    with pytest.raises(NotFoundError):
        await harness.receive(provider="someone-else")

    assert harness.webhook.calls == []


async def test_a_provider_that_cannot_talk_to_us_says_so() -> None:
    without_inbound = PaymentService(
        transactions=InMemoryTransactionRepository(),
        orders=InMemoryOrderRepository(),
        refunds=InMemoryRefundRepository(),
        webhook_events=InMemoryWebhookEventRepository(),
        gateway=FakeGateway(),
    )

    with pytest.raises(ProviderNotConfiguredError):
        await without_inbound.handle_webhook(
            provider=PROVIDER, payload=PAYLOAD, headers={}
        )


# --- the same event again -----------------------------------------------------


async def test_a_redelivered_event_changes_nothing_twice() -> None:
    harness = await _harness()

    await harness.receive()
    after_first = (harness.order.status, harness.transaction.status)
    second, outcome = await harness.receive()

    assert outcome.value == "duplicate"
    assert (harness.order.status, harness.transaction.status) == after_first
    # Exactly one receipt, exactly one transaction: nothing was duplicated.
    assert len(harness.transactions._store) == 1
    assert len(harness.events._store) == 1
    assert second.event_id == "evt-1"


async def test_a_second_event_announcing_the_same_news_changes_nothing() -> None:
    """Different event id, same fact: the ledger already agrees, so nothing moves."""
    harness = await _harness()
    await harness.receive()

    harness.webhook.notification = _notification(
        event_id="evt-2", reference=harness.transaction.reference
    )
    _, outcome = await harness.receive()

    assert outcome.value == "applied"
    assert harness.transaction.status is PaymentStatus.PAID
    assert harness.order.status is OrderStatus.PAID
    assert len(harness.events._store) == 2


async def test_the_idempotency_key_is_the_provider_and_the_event_together() -> None:
    """Two providers may each mint an id our store has already seen."""
    harness = await _harness()
    await harness.receive()

    from_another_provider = await harness.events.add(
        WebhookEvent(
            id=0, provider="other", event_id="evt-1", kind=WebhookKind.PAYMENT_PAID
        )
    )

    assert len(harness.events._store) == 2
    assert from_another_provider.processed is False


# --- an event that contradicts the ledger -------------------------------------


async def test_a_late_failure_cannot_unpay_a_paid_order() -> None:
    harness = await _harness()
    await harness.receive()

    harness.webhook.notification = _notification(
        event_id="evt-2",
        kind=WebhookKind.PAYMENT_FAILED,
        reference=harness.transaction.reference,
        amount=None,
    )
    _, outcome = await harness.receive()

    # Recorded, acknowledged, and refused: the money arrived, and a provider
    # changing its mind afterwards is not something we undo silently.
    assert outcome.value == "disputed"
    assert harness.transaction.status is PaymentStatus.PAID
    assert harness.order.status is OrderStatus.PAID


async def test_an_event_naming_a_different_amount_is_not_acted_on() -> None:
    harness = await _harness(amount=Decimal("1.00"))

    _, outcome = await harness.receive()

    assert outcome.value == "disputed"
    assert harness.transaction.status is PaymentStatus.PENDING
    assert harness.order.status is OrderStatus.PENDING_PAYMENT


async def test_an_event_for_a_payment_whose_order_has_gone_is_disputed() -> None:
    """Nothing is settled into a payment that no longer belongs to an order."""
    harness = await _harness()
    harness.orders._store.clear()

    _, outcome = await harness.receive()

    assert outcome.value == "disputed"
    assert harness.transaction.status is PaymentStatus.PENDING


# --- a verification and a webhook are the same conversation -------------------


async def test_a_webhook_confirms_what_the_customer_was_told_by_verification() -> None:
    harness = await _harness()

    await harness.service.verify(
        user_id=USER_ID, reference=harness.transaction.reference
    )
    _, outcome = await harness.receive()

    assert outcome.value == "applied"
    assert harness.transaction.status is PaymentStatus.PAID
    assert harness.order.status is OrderStatus.PAID

# --- what a notification tells the store --------------------------------------


async def test_an_event_that_pays_an_order_announces_it_once() -> None:
    harness = await _harness()

    await harness.receive()

    assert [message.to for message in harness.emails.calls] == [OWNER]
    assert harness.transaction.reference in harness.emails.calls[0].text_body


async def test_a_redelivered_event_announces_nothing_again() -> None:
    """A repeated event has no business effect at all -- including an email."""
    harness = await _harness()

    await harness.receive()
    await harness.receive()

    assert len(harness.emails.calls) == 1


async def test_a_second_event_bringing_the_same_news_is_not_second_news() -> None:
    """Announcing hangs off the transition, not off a message id.

    Two different events saying the order is paid tell the store once: an order
    becomes paid exactly once, and that is the only moment there is news to give.
    """
    harness = await _harness()
    await harness.receive()
    harness.webhook.notification = _notification(
        reference=harness.transaction.reference, event_id="evt-2"
    )

    _, outcome = await harness.receive()

    assert outcome.value == "applied"
    assert len(harness.emails.calls) == 1


async def test_an_event_that_paid_nothing_announces_nothing() -> None:
    harness = await _harness(kind=WebhookKind.PAYMENT_FAILED)

    await harness.receive()

    assert harness.emails.calls == []
