"""PaymentService orchestration against a mocked gateway (no provider, no DB).

The point of these tests is that the service only ever sees the contract: the
same calls produce the same behaviour for two structurally different fake
providers, because nothing in the service is provider-aware.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domains.orders.domain.entities import Order, OrderItem
from app.domains.orders.domain.enums import OrderStatus
from app.domains.orders.domain.repositories import AbstractOrderRepository
from app.domains.payments.application.notifications import PaidOrderNotifier
from app.domains.payments.application.service import PaymentService
from app.domains.payments.domain.entities import Refund, Transaction, WebhookEvent
from app.domains.payments.domain.enums import (
    PaymentAction,
    PaymentStatus,
    RefundStatus,
)
from app.domains.payments.domain.gateway import (
    AbstractPaymentGateway,
    PaymentInitiation,
    PaymentRequest,
    PaymentVerification,
    RefundRequest,
    RefundResult,
)
from app.domains.payments.domain.repositories import (
    AbstractRefundRepository,
    AbstractTransactionRepository,
    AbstractWebhookEventRepository,
)
from app.shared.exceptions import ConflictError, NotFoundError
from tests.unit.payments.test_order_notification import OWNER, RecordingSender

USER_ID = 7
OTHER_USER = 8
AMOUNT = Decimal("42000.00")


class FakeGateway(AbstractPaymentGateway):
    """A provider double whose every answer the test dictates."""

    provider = "fake"

    def __init__(
        self,
        *,
        initiation: PaymentInitiation | None = None,
        verification: PaymentVerification | None = None,
        refund: RefundResult | None = None,
    ) -> None:
        self.initiation = initiation or PaymentInitiation(
            success=True,
            status=PaymentStatus.PENDING,
            provider_reference="prov-77",
            checkout_url="https://provider.example/pay/prov-77",
            action=PaymentAction.REDIRECT,
        )
        self.verification = verification
        self.refund = refund
        self.requests: list[PaymentRequest] = []
        self.verified: list[str] = []
        self.refunds: list[RefundRequest] = []

    async def create_payment(self, request: PaymentRequest) -> PaymentInitiation:
        self.requests.append(request)
        return self.initiation

    async def verify_payment(self, reference: str) -> PaymentVerification:
        self.verified.append(reference)
        return self.verification or PaymentVerification(
            success=True,
            status=PaymentStatus.PAID,
            transaction_reference=reference,
            provider_reference="prov-77",
            amount=AMOUNT,
        )

    async def refund_payment(self, request: RefundRequest) -> RefundResult:
        self.refunds.append(request)
        return self.refund or RefundResult(
            success=True,
            status=PaymentStatus.REFUNDED,
            transaction_reference=request.transaction_reference,
            provider_refund_reference="rf-1",
            amount=request.amount,
        )


class InMemoryOrderRepository(AbstractOrderRepository):
    def __init__(self, *orders: Order) -> None:
        self._store = {order.id: order for order in orders}

    async def add(self, order: Order) -> Order:  # pragma: no cover - unused
        self._store[order.id] = order
        return order

    async def get_by_id(self, order_id: int) -> Order | None:
        return self._store.get(order_id)

    async def list_by_user_id(self, user_id: int) -> list[Order]:  # pragma: no cover
        return [o for o in self._store.values() if o.user_id == user_id]

    async def list_all(self, *, limit: int, offset: int) -> list[Order]:  # pragma: no cover
        return list(self._store.values())[offset : offset + limit]

    async def count_all(self, *, status: OrderStatus | None = None) -> int:  # pragma: no cover
        return sum(1 for o in self._store.values() if status is None or o.status is status)

    async def save(self, order: Order) -> Order:
        # A single aggregate held by reference: the stored object is the saved one.
        self._store[order.id] = order
        return order


class InMemoryTransactionRepository(AbstractTransactionRepository):
    def __init__(self) -> None:
        self._store: dict[int, Transaction] = {}
        self._next = 500

    async def add(self, transaction: Transaction) -> Transaction:
        transaction.id = self._next
        self._next += 1
        self._store[transaction.id] = transaction
        return transaction

    async def get_by_id(self, transaction_id: int) -> Transaction | None:
        return self._store.get(transaction_id)

    async def get_by_reference(self, reference: str) -> Transaction | None:
        return next(
            (t for t in self._store.values() if t.reference == reference), None
        )

    async def get_latest_by_order_id(self, order_id: int) -> Transaction | None:
        matches = [t for t in self._store.values() if t.order_id == order_id]
        return max(matches, key=lambda t: t.id) if matches else None

    async def save(self, transaction: Transaction) -> Transaction:
        # A single-row aggregate: the stored object is the persisted one.
        self._store[transaction.id] = transaction
        return transaction


class InMemoryRefundRepository(AbstractRefundRepository):
    def __init__(self) -> None:
        self._store: dict[int, Refund] = {}
        self._next = 900

    async def add(self, refund: Refund) -> Refund:
        refund.id = self._next
        self._next += 1
        self._store[refund.id] = refund
        return refund

    async def get_by_reference(self, reference: str) -> Refund | None:
        return next((r for r in self._store.values() if r.reference == reference), None)

    async def list_by_transaction_id(self, transaction_id: int) -> list[Refund]:
        return [r for r in self._store.values() if r.transaction_id == transaction_id]

    async def total_refunded(self, transaction_id: int) -> Decimal:
        return sum(
            (
                r.amount
                for r in self._store.values()
                if r.transaction_id == transaction_id and r.is_settled
            ),
            Decimal("0.00"),
        )


class InMemoryWebhookEventRepository(AbstractWebhookEventRepository):
    """Mimics the database's uniqueness on (provider, event_id)."""

    def __init__(self) -> None:
        self._store: dict[int, WebhookEvent] = {}
        self._next = 700

    async def add(self, event: WebhookEvent) -> WebhookEvent:
        dupe = await self.get_by_provider_and_event_id(event.provider, event.event_id)
        if dupe is not None:
            raise AssertionError(f"event {event.event_id} recorded twice")
        event.id = self._next
        self._next += 1
        self._store[event.id] = event
        return event

    async def get_by_provider_and_event_id(
        self, provider: str, event_id: str
    ) -> WebhookEvent | None:
        return next(
            (
                e
                for e in self._store.values()
                if e.provider == provider and e.event_id == event_id
            ),
            None,
        )

    async def save(self, event: WebhookEvent) -> WebhookEvent:
        self._store[event.id] = event
        return event


def _order(
    *, user_id: int = USER_ID, status: OrderStatus = OrderStatus.PENDING_PAYMENT
) -> Order:
    return Order(
        id=10,
        reference="ZD-ABC12345",
        user_id=user_id,
        status=status,
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


def _service(
    *,
    order: Order | None = None,
    gateway: FakeGateway | None = None,
    orders: AbstractOrderRepository | None = None,
    refunds: AbstractRefundRepository | None = None,
    notifier: PaidOrderNotifier | None = None,
    provider: str | None = None,
) -> tuple[PaymentService, InMemoryTransactionRepository, FakeGateway]:
    order = order if order is not None else _order()
    transactions = InMemoryTransactionRepository()
    gateway = gateway or FakeGateway()
    service = PaymentService(
        transactions=transactions,
        orders=orders or InMemoryOrderRepository(order),
        refunds=refunds or InMemoryRefundRepository(),
        webhook_events=InMemoryWebhookEventRepository(),
        gateway=gateway,
        notifier=notifier,
        provider=provider,
    )
    return service, transactions, gateway


def _notifier(
    *, owner_email: str = OWNER, sender: RecordingSender | None = None
) -> tuple[PaidOrderNotifier, RecordingSender]:
    """A wired-up notification capability, and the recorder to read afterwards."""
    emails = sender or RecordingSender()
    return PaidOrderNotifier(sender=emails, owner_email=owner_email), emails


# --- initiation -------------------------------------------------------------


async def test_initiation_creates_a_pending_transaction() -> None:
    service, transactions, gateway = _service()

    transaction, result = await service.initiate(user_id=USER_ID, order_id=10)

    assert result.success is True
    assert transaction.status is PaymentStatus.PENDING
    assert transaction.amount == AMOUNT  # taken from the order, not the client
    assert transaction.currency == "NGN"
    assert transaction.order_id == 10
    assert transaction.reference.startswith("PAY-")
    assert transaction.provider_reference == "prov-77"
    assert transaction.checkout_url == "https://provider.example/pay/prov-77"
    # What the service asked the provider for, in provider-independent terms.
    request = gateway.requests[0]
    assert (request.email, request.order_reference) == ("ada@example.com", "ZD-ABC12345")
    assert request.reference == transaction.reference


async def test_initiation_is_labelled_from_configuration() -> None:
    service, _, _ = _service(provider="configured-one")

    transaction, _ = await service.initiate(user_id=USER_ID, order_id=10)

    assert transaction.provider == "configured-one"


async def test_initiation_reuses_an_open_transaction() -> None:
    service, transactions, _ = _service()

    first, _ = await service.initiate(user_id=USER_ID, order_id=10)
    second, _ = await service.initiate(user_id=USER_ID, order_id=10)

    assert second.reference == first.reference
    assert len(transactions._store) == 1


async def test_initiation_of_another_users_order_is_not_found() -> None:
    service, transactions, gateway = _service()

    with pytest.raises(NotFoundError):
        await service.initiate(user_id=OTHER_USER, order_id=10)

    assert transactions._store == {}
    assert gateway.requests == []


async def test_initiation_of_an_unknown_order_is_not_found() -> None:
    service, _, _ = _service()

    with pytest.raises(NotFoundError):
        await service.initiate(user_id=USER_ID, order_id=999)


async def test_order_that_is_not_awaiting_payment_cannot_be_paid_again() -> None:
    service, _, gateway = _service(order=_order(status=OrderStatus.PAID))

    with pytest.raises(ConflictError):
        await service.initiate(user_id=USER_ID, order_id=10)

    assert gateway.requests == []


async def test_failed_initiation_is_recorded_and_retried_with_a_new_attempt() -> None:
    failing = FakeGateway(
        initiation=PaymentInitiation(
            success=False, status=PaymentStatus.FAILED, message="Provider declined"
        )
    )
    service, transactions, _ = _service(gateway=failing)

    transaction, result = await service.initiate(user_id=USER_ID, order_id=10)

    assert result.success is False
    assert transaction.status is PaymentStatus.FAILED
    assert transaction.failure_reason == "Provider declined"

    # Retrying starts a fresh attempt rather than reviving the dead one.
    retry_service = PaymentService(
        transactions=transactions,
        orders=InMemoryOrderRepository(_order()),
        refunds=InMemoryRefundRepository(),
        webhook_events=InMemoryWebhookEventRepository(),
        gateway=FakeGateway(),
    )
    retried, _ = await retry_service.initiate(user_id=USER_ID, order_id=10)

    assert retried.status is PaymentStatus.PENDING
    assert retried.reference != transaction.reference
    assert len(transactions._store) == 2


async def test_already_paid_order_cannot_be_initiated_again() -> None:
    service, transactions, gateway = _service()
    await service.initiate(user_id=USER_ID, order_id=10)
    paid = next(iter(transactions._store.values()))
    paid.mark_paid()

    with pytest.raises(ConflictError):
        await service.initiate(user_id=USER_ID, order_id=10)

    assert len(gateway.requests) == 1


# --- verification -----------------------------------------------------------


async def test_verification_settles_the_transaction() -> None:
    service, _, gateway = _service()
    transaction, _ = await service.initiate(user_id=USER_ID, order_id=10)

    settled, result = await service.verify(user_id=USER_ID, reference=transaction.reference)

    assert result.success is True
    assert settled.status is PaymentStatus.PAID
    assert gateway.verified == [transaction.reference]


async def test_a_confirmed_payment_settles_the_order_it_paid_for() -> None:
    order = _order()
    service, _, _ = _service(order=order)
    transaction, _ = await service.initiate(user_id=USER_ID, order_id=10)

    await service.verify(user_id=USER_ID, reference=transaction.reference)

    assert order.status is OrderStatus.PAID


async def test_a_declined_payment_leaves_the_order_awaiting_payment() -> None:
    order = _order()
    gateway = FakeGateway(
        verification=PaymentVerification(
            success=True, status=PaymentStatus.FAILED, message="Insufficient funds"
        )
    )
    service, _, _ = _service(order=order, gateway=gateway)
    transaction, _ = await service.initiate(user_id=USER_ID, order_id=10)

    await service.verify(user_id=USER_ID, reference=transaction.reference)

    # A failed attempt is not a failed order: the customer may try again.
    assert order.status is OrderStatus.PENDING_PAYMENT


async def test_a_provider_confirming_a_different_amount_is_believed_by_nobody() -> None:
    order = _order()
    gateway = FakeGateway(
        verification=PaymentVerification(
            success=True,
            status=PaymentStatus.PAID,
            transaction_reference="PAY-1",
            amount=Decimal("1.00"),
        )
    )
    service, transactions, _ = _service(order=order, gateway=gateway)
    transaction, _ = await service.initiate(user_id=USER_ID, order_id=10)

    with pytest.raises(ConflictError):
        await service.verify(user_id=USER_ID, reference=transaction.reference)

    assert transaction.status is PaymentStatus.PENDING
    assert order.status is OrderStatus.PENDING_PAYMENT
    assert transactions._store[transaction.id].status is PaymentStatus.PENDING


async def test_replaying_a_settled_verification_changes_nothing() -> None:
    service, _, _ = _service()
    transaction, _ = await service.initiate(user_id=USER_ID, order_id=10)
    await service.verify(user_id=USER_ID, reference=transaction.reference)

    again, _ = await service.verify(user_id=USER_ID, reference=transaction.reference)

    assert again.status is PaymentStatus.PAID


async def test_verification_reports_a_declined_payment() -> None:
    gateway = FakeGateway(
        verification=PaymentVerification(
            success=True,
            status=PaymentStatus.FAILED,
            transaction_reference="PAY-1",
            message="Card declined",
        )
    )
    service, _, _ = _service(gateway=gateway)
    transaction, _ = await service.initiate(user_id=USER_ID, order_id=10)

    settled, result = await service.verify(user_id=USER_ID, reference=transaction.reference)

    assert result.success is True  # the check worked...
    assert settled.status is PaymentStatus.FAILED  # ...the money did not arrive
    assert settled.failure_reason == "Card declined"


async def test_unreachable_provider_leaves_the_attempt_open() -> None:
    gateway = FakeGateway(
        verification=PaymentVerification(
            success=False, status=PaymentStatus.PENDING, message="Provider timeout"
        )
    )
    service, _, _ = _service(gateway=gateway)
    transaction, _ = await service.initiate(user_id=USER_ID, order_id=10)

    settled, result = await service.verify(user_id=USER_ID, reference=transaction.reference)

    assert result.success is False
    assert settled.status is PaymentStatus.PENDING


async def test_verification_of_another_users_payment_is_not_found() -> None:
    service, _, gateway = _service()
    transaction, _ = await service.initiate(user_id=USER_ID, order_id=10)

    with pytest.raises(NotFoundError):
        await service.verify(user_id=OTHER_USER, reference=transaction.reference)

    assert gateway.verified == []


async def test_verification_of_an_unknown_reference_is_not_found() -> None:
    service, _, _ = _service()

    with pytest.raises(NotFoundError):
        await service.verify(user_id=USER_ID, reference="PAY-nope")


# --- notification ------------------------------------------------------------


async def test_a_payment_the_provider_confirmed_is_announced_once() -> None:
    """The service tells the notifier that an order became paid. Nothing more."""
    notifier, emails = _notifier()
    service, _, _ = _service(notifier=notifier)
    transaction, _ = await service.initiate(user_id=USER_ID, order_id=10)

    await service.verify(user_id=USER_ID, reference=transaction.reference)

    assert [message.to for message in emails.calls] == [OWNER]
    body = emails.calls[0].text_body
    assert "ZD-ABC12345" in body and transaction.reference in body


async def test_a_declined_payment_is_not_announced() -> None:
    notifier, emails = _notifier()
    gateway = FakeGateway(
        verification=PaymentVerification(
            success=True, status=PaymentStatus.FAILED, message="Card declined"
        )
    )
    service, _, _ = _service(gateway=gateway, notifier=notifier)
    transaction, _ = await service.initiate(user_id=USER_ID, order_id=10)

    await service.verify(user_id=USER_ID, reference=transaction.reference)

    assert emails.calls == []


async def test_an_answer_that_proved_nothing_sends_nobody_anywhere() -> None:
    notifier, emails = _notifier()
    gateway = FakeGateway(
        verification=PaymentVerification(
            success=False, status=PaymentStatus.PENDING, message="Provider timeout"
        )
    )
    service, _, _ = _service(gateway=gateway, notifier=notifier)
    transaction, _ = await service.initiate(user_id=USER_ID, order_id=10)

    await service.verify(user_id=USER_ID, reference=transaction.reference)

    assert emails.calls == []


async def test_hearing_the_same_news_twice_announces_it_once() -> None:
    notifier, emails = _notifier()
    service, _, _ = _service(notifier=notifier)
    transaction, _ = await service.initiate(user_id=USER_ID, order_id=10)

    await service.verify(user_id=USER_ID, reference=transaction.reference)
    await service.verify(user_id=USER_ID, reference=transaction.reference)

    assert len(emails.calls) == 1


async def test_a_store_with_no_notifier_still_settles_its_payments() -> None:
    """Notifications are something a deployment may not have, not may not pay."""
    service, _, _ = _service()
    transaction, _ = await service.initiate(user_id=USER_ID, order_id=10)

    settled, _ = await service.verify(user_id=USER_ID, reference=transaction.reference)

    assert settled.status is PaymentStatus.PAID


# --- refunds ---------------------------------------------------------------


async def test_refund_settles_back_to_the_customer() -> None:
    service, _, _ = _service()
    transaction, _ = await service.initiate(user_id=USER_ID, order_id=10)
    await service.verify(user_id=USER_ID, reference=transaction.reference)

    settled, result = await service.refund(reference=transaction.reference)

    assert result.success is True
    assert settled.status is PaymentStatus.REFUNDED


async def test_a_second_full_refund_is_refused() -> None:
    service, _, gateway = _service()
    transaction, _ = await service.initiate(user_id=USER_ID, order_id=10)
    await service.verify(user_id=USER_ID, reference=transaction.reference)
    await service.refund(reference=transaction.reference)

    with pytest.raises(ConflictError):
        await service.refund(reference=transaction.reference)

    assert len(gateway.refunds) == 1


async def test_refund_amount_and_reason_are_passed_through() -> None:
    ledger = InMemoryRefundRepository()
    service, _, gateway = _service(refunds=ledger)
    transaction, _ = await service.initiate(user_id=USER_ID, order_id=10)
    await service.verify(user_id=USER_ID, reference=transaction.reference)

    settled, _ = await service.refund(
        reference=transaction.reference, amount=Decimal("1000.00"), reason="One jersey"
    )

    request = gateway.refunds[0]
    assert request.amount == Decimal("1000.00")
    assert request.reason == "One jersey"
    # Only part of the money went back, so the payment is still mostly paid --
    # the refund itself is what the ledger remembers.
    assert settled.status is PaymentStatus.PAID
    (entry,) = await ledger.list_by_transaction_id(transaction.id)
    assert entry.amount == Decimal("1000.00")
    assert entry.reason == "One jersey"
    assert entry.status is RefundStatus.SUCCEEDED
    assert entry.reference.startswith("RFD-")


async def test_a_full_refund_asks_the_provider_for_its_whole_balance() -> None:
    service, _, gateway = _service()
    transaction, _ = await service.initiate(user_id=USER_ID, order_id=10)
    await service.verify(user_id=USER_ID, reference=transaction.reference)

    settled, _ = await service.refund(reference=transaction.reference)

    # No figure is sent: Stripe/Paystack refund what they hold, so a rounding
    # difference cannot make a "full" refund come up short.
    assert gateway.refunds[0].amount is None
    assert settled.status is PaymentStatus.REFUNDED


async def test_successive_refunds_cannot_outrun_the_payment() -> None:
    ledger = InMemoryRefundRepository()
    service, _, gateway = _service(refunds=ledger)
    transaction, _ = await service.initiate(user_id=USER_ID, order_id=10)
    await service.verify(user_id=USER_ID, reference=transaction.reference)

    half = AMOUNT / 2
    await service.refund(reference=transaction.reference, amount=half)

    # The second refund can reach what is left, and not a kobo more.
    with pytest.raises(ConflictError):
        await service.refund(reference=transaction.reference, amount=half + Decimal("1.00"))
    assert len(gateway.refunds) == 1

    settled, _ = await service.refund(
        reference=transaction.reference, amount=half, reason="The other jersey"
    )
    assert settled.status is PaymentStatus.REFUNDED
    assert len(await ledger.list_by_transaction_id(transaction.id)) == 2


async def test_an_uncharged_refund_is_not_written_into_the_ledger() -> None:
    gateway = FakeGateway(
        refund=RefundResult(
            success=False, status=PaymentStatus.PAID, message="Card network refused"
        )
    )
    ledger = InMemoryRefundRepository()
    service, _, _ = _service(gateway=gateway, refunds=ledger)
    transaction, _ = await service.initiate(user_id=USER_ID, order_id=10)
    await service.verify(user_id=USER_ID, reference=transaction.reference)

    await service.refund(reference=transaction.reference)

    assert await ledger.list_by_transaction_id(transaction.id) == []


async def test_failed_refund_leaves_the_payment_untouched() -> None:
    gateway = FakeGateway(
        refund=RefundResult(
            success=False,
            status=PaymentStatus.PAID,
            message="Refund window closed",
        )
    )
    service, _, _ = _service(gateway=gateway)
    transaction, _ = await service.initiate(user_id=USER_ID, order_id=10)
    await service.verify(user_id=USER_ID, reference=transaction.reference)

    settled, result = await service.refund(reference=transaction.reference)

    assert result.success is False
    assert settled.status is PaymentStatus.PAID


async def test_only_a_paid_payment_can_be_refunded() -> None:
    service, _, _ = _service()
    transaction, _ = await service.initiate(user_id=USER_ID, order_id=10)

    with pytest.raises(ConflictError):
        await service.refund(reference=transaction.reference)


async def test_refund_of_an_unknown_reference_is_not_found() -> None:
    service, _, _ = _service()

    with pytest.raises(NotFoundError):
        await service.refund(reference="PAY-nope")


# --- provider swap-ability --------------------------------------------------


class AnotherFakeGateway(FakeGateway):
    """A second, structurally different provider behind the same contract."""

    provider = "other-fake"

    async def create_payment(self, request: PaymentRequest) -> PaymentInitiation:
        self.requests.append(request)
        return PaymentInitiation(
            success=True,
            status=PaymentStatus.PENDING,
            provider_reference="other-1",
            checkout_url="https://other.example/checkout",
            action=PaymentAction.REDIRECT,
        )


@pytest.mark.parametrize("gateway_factory", [FakeGateway, AnotherFakeGateway])
async def test_the_same_service_code_drives_any_provider(
    gateway_factory: type[FakeGateway],
) -> None:
    service, _, _ = _service(gateway=gateway_factory())

    transaction, result = await service.initiate(user_id=USER_ID, order_id=10)
    settled, verification = await service.verify(
        user_id=USER_ID, reference=transaction.reference
    )

    assert result.success is True
    assert settled.status is PaymentStatus.PAID
    assert verification.status is PaymentStatus.PAID
    assert settled.provider == transaction.provider
