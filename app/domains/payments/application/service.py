"""Payments application service.

The service talks to a gateway *contract* only. It never learns whether the
provider is Paystack, Stripe or the test double: it asks for a payment, records
what came back in its own transaction vocabulary, and hands the caller a
normalised result. That is what makes the provider swappable without touching
this file.

Confirmation is the other half of the job, and it has two entrances -- the
customer asking "did it go through?" and the provider telling us unprompted.
Both funnel through one private settlement path, so an order can only become
paid by the same rules, and so a redelivered webhook cannot pay for an order
twice. Every provider notification is recorded before it is acted on, because
the record of what we have already seen is what makes the second arrival a
no-op.

Telling the store about money that has arrived is a notification, not part of
settlement: this service asks a notifier to do it, on the one transition where
an order becomes paid, and never learns which email provider hears about it.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from uuid import uuid4

from app.domains.orders.domain.entities import Order
from app.domains.orders.domain.repositories import AbstractOrderRepository
from app.domains.payments.application.notifications import PaidOrderNotifier
from app.domains.payments.domain.entities import (
    Refund,
    Transaction,
    WebhookEvent,
)
from app.domains.payments.domain.enums import (
    PaymentStatus,
    RefundStatus,
    WebhookKind,
    WebhookOutcome,
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
from app.domains.payments.domain.webhooks import (
    AbstractWebhookAdapter,
    WebhookNotification,
)
from app.shared.exceptions import (
    ConflictError,
    NotFoundError,
    ProviderNotConfiguredError,
)

_REFERENCE_PREFIX = "PAY-"
_REFUND_REFERENCE_PREFIX = "RFD-"

#: The notification kinds this application knows how to act on. Refunds are not
#: one of them: a refund we started is already in the ledger, and one we did not
#: start is not news we may act on by guessing.
_ACTIONABLE = (WebhookKind.PAYMENT_PAID, WebhookKind.PAYMENT_FAILED)


def new_payment_reference() -> str:
    """The internal reference the provider is pointed at."""
    return f"{_REFERENCE_PREFIX}{uuid4().hex[:12].upper()}"


def new_refund_reference() -> str:
    """The internal reference for one refund of a payment."""
    return f"{_REFUND_REFERENCE_PREFIX}{uuid4().hex[:12].upper()}"


class PaymentService:
    def __init__(
        self,
        *,
        transactions: AbstractTransactionRepository,
        orders: AbstractOrderRepository,
        refunds: AbstractRefundRepository,
        webhook_events: AbstractWebhookEventRepository,
        gateway: AbstractPaymentGateway,
        webhook: AbstractWebhookAdapter | None = None,
        notifier: PaidOrderNotifier | None = None,
        provider: str | None = None,
    ) -> None:
        self._transactions = transactions
        self._orders = orders
        self._refunds = refunds
        self._webhook_events = webhook_events
        self._gateway = gateway
        # Composition decides whether the configured provider can also talk to us
        # (an adapter implements both contracts); the service is simply told.
        self._webhook = webhook
        # The same for the store's own newsdesk: absent means a deployment that
        # has not configured notifications, not a payment nobody should hear about.
        self._notifier = notifier
        # Configuration names the provider; the gateway contract stays anonymous.
        self._provider = provider or gateway.provider

    async def initiate(
        self, *, user_id: int, order_id: int
    ) -> tuple[Transaction, PaymentInitiation]:
        """Open (or reopen) a payment for one of the caller's unpaid orders."""
        order = await self._own_order(user_id=user_id, order_id=order_id)
        if not order.is_pending_payment:
            raise ConflictError("This order is not awaiting payment")

        transaction = await self._transactions.get_latest_by_order_id(order.id)
        if transaction is not None and transaction.is_paid:
            raise ConflictError("This order has already been paid")
        if transaction is None or transaction.status is PaymentStatus.FAILED:
            transaction = await self._transactions.add(
                self._new_transaction(order)
            )

        result = await self._gateway.create_payment(self._request_for(order, transaction))
        if result.success:
            transaction.attach_initiation(
                provider_reference=result.provider_reference,
                checkout_url=result.checkout_url,
            )
        else:
            transaction.mark_failed(result.message)
        return await self._transactions.save(transaction), result

    async def verify(
        self, *, user_id: int, reference: str
    ) -> tuple[Transaction, PaymentVerification]:
        """Ask the provider whether a payment went through and record the answer.

        An unreachable provider leaves the transaction pending: "unknown" is
        never upgraded into success or failure here. A provider that confirms a
        different amount than the order asked for is refused rather than trusted.
        """
        transaction = await self._own_transaction(user_id=user_id, reference=reference)

        result = await self._gateway.verify_payment(reference)
        if not result.success:
            return transaction, result
        await self._settle(
            transaction,
            status=result.status,
            provider_reference=result.provider_reference,
            amount=result.amount,
            reason=result.message,
        )
        return transaction, result

    async def refund(
        self,
        *,
        reference: str,
        amount: Decimal | None = None,
        reason: str | None = None,
    ) -> tuple[Transaction, RefundResult]:
        """Refund a settled payment, in part or in full, and ledger what went back.

        Without the ledger a payment could be refunded repeatedly until the
        provider complained; here the outstanding balance is known locally, and a
        second refund can only ever reach what the first one left.
        """
        transaction = await self._transactions.get_by_reference(reference)
        if transaction is None:
            raise NotFoundError("Payment not found")
        if not transaction.is_paid:
            raise ConflictError("Only a paid payment can be refunded")

        already = await self._refunds.total_refunded(transaction.id)
        refundable = transaction.refundable_amount(already)
        whole_payment = already == Decimal("0")
        if amount is None:
            amount = refundable
        elif amount > refundable:
            raise ConflictError(
                f"Only {refundable} {transaction.currency} of this payment is left to refund"
            )

        result = await self._gateway.refund_payment(
            RefundRequest(
                transaction_reference=reference,
                # "Everything" is left to the provider to total, so a rounding
                # difference cannot make a full refund come up short.
                amount=None if whole_payment and amount == transaction.amount else amount,
                reason=reason,
            )
        )
        if not result.success:
            return transaction, result

        await self._refunds.add(
            self._new_refund(transaction, amount=amount, reason=reason, result=result)
        )
        if amount >= refundable:
            transaction.mark_refunded(result.provider_refund_reference)
        # A partial refund leaves the payment paid: some money is still ours.
        return await self._transactions.save(transaction), result

    async def handle_webhook(
        self, *, provider: str, payload: bytes, headers: Mapping[str, str]
    ) -> tuple[WebhookEvent, WebhookOutcome]:
        """Take one provider notification: authenticate, record, act on it once.

        The order of those three steps is the whole idempotency story. A payload
        that is not authentically from the provider never reaches the ledger.
        An authentic one is recorded under the provider's own event id *before*
        anything is changed, so a redelivery is recognised as the same news and
        returns without touching a transaction, an order or a stock level. A
        notification that contradicts this store is recorded and left alone --
        raising would make the provider redeliver a message we have already
        decided not to act on.
        """
        adapter = self._webhook
        if adapter is None:
            raise ProviderNotConfiguredError(
                f"Provider '{self._provider}' cannot receive webhook notifications."
            )
        if provider.strip().lower() != adapter.provider:
            # Only the configured provider gets to talk about its own payments.
            raise NotFoundError("Unknown payment provider")

        notification = adapter.parse_notification(payload=payload, headers=headers)
        receipt = await self._webhook_events.get_by_provider_and_event_id(
            notification.provider, notification.event_id
        )
        if receipt is not None:
            return receipt, WebhookOutcome.DUPLICATE
        receipt = await self._webhook_events.add(self._new_receipt(notification))

        if notification.kind not in _ACTIONABLE:
            return receipt, WebhookOutcome.IGNORED
        transaction = (
            await self._transactions.get_by_reference(notification.reference or "")
            if notification.names_our_payment
            else None
        )
        if transaction is None:
            return receipt, WebhookOutcome.UNMATCHED

        try:
            await self._settle(
                transaction,
                status=(
                    PaymentStatus.PAID
                    if notification.kind is WebhookKind.PAYMENT_PAID
                    else PaymentStatus.FAILED
                ),
                provider_reference=notification.provider_reference,
                amount=notification.amount,
                reason=notification.message,
            )
        except (ConflictError, NotFoundError):
            return receipt, WebhookOutcome.DISPUTED
        receipt.mark_processed(transaction_id=transaction.id)
        return await self._webhook_events.save(receipt), WebhookOutcome.APPLIED

    async def _settle(
        self,
        transaction: Transaction,
        *,
        status: PaymentStatus,
        provider_reference: str | None = None,
        amount: Decimal | None = None,
        reason: str | None = None,
    ) -> bool:
        """Record one confirmed provider outcome, and cascade a payment to the order.

        Returns whether this call moved the transaction. Being already in the
        reported state is a success, not a conflict: that is what lets a
        verification and its provider's webhook both announce the same payment.
        """
        if status not in (PaymentStatus.PAID, PaymentStatus.FAILED):
            # Still pending: an inconclusive answer changes nothing here.
            return False
        if status is PaymentStatus.PAID:
            self._require_matching_amount(transaction, amount)
        # Load the order before mutating anything, so a transaction whose order
        # has gone cannot be half-settled.
        order = await self._orders.get_by_id(transaction.order_id)
        if order is None:
            raise NotFoundError("The order behind this payment no longer exists")

        before = transaction.status
        if status is PaymentStatus.PAID:
            transaction.mark_paid(provider_reference)
        else:
            transaction.mark_failed(reason)
        changed = transaction.status is not before
        await self._transactions.save(transaction)
        if status is PaymentStatus.PAID and order.mark_paid():
            await self._orders.save(order)
            # The transition is the trigger: announcing a payment here means one
            # email per paid order, however many times the provider repeats it.
            await self._notify_paid(order, transaction)
        return changed

    async def _notify_paid(self, order: Order, transaction: Transaction) -> None:
        """Tell the store about a payment that has just become confirmed.

        The notifier is given the order and the payment and decides what to say
        and who to say it to; this service holds no email knowledge of its own and
        cannot be failed by an email that does not go out.
        """
        if self._notifier is None:
            return
        await self._notifier.notify_paid(order=order, transaction=transaction)

    @staticmethod
    def _require_matching_amount(
        transaction: Transaction, amount: Decimal | None
    ) -> None:
        """Refuse to confirm a payment for a figure other than the one asked for."""
        if amount is not None and amount != transaction.amount:
            raise ConflictError(
                "The provider confirmed a different amount than this payment asked for"
            )

    def _new_transaction(self, order: Order) -> Transaction:
        transaction = Transaction(
            id=0,
            reference=new_payment_reference(),
            order_id=order.id,
            amount=order.total,
            currency=order.currency,
            provider=self._provider,
        )
        transaction.validate()
        return transaction

    def _new_refund(
        self,
        transaction: Transaction,
        *,
        amount: Decimal,
        reason: str | None,
        result: RefundResult,
    ) -> Refund:
        """One ledger line for money the provider agreed to send back."""
        refund = Refund(
            id=0,
            reference=new_refund_reference(),
            transaction_id=transaction.id,
            amount=amount,
            currency=transaction.currency,
            provider=self._provider,
            status=RefundStatus.SUCCEEDED,
            provider_refund_reference=result.provider_refund_reference,
            reason=reason,
        )
        refund.validate()
        return refund

    @staticmethod
    def _new_receipt(notification: WebhookNotification) -> WebhookEvent:
        """The record that this provider event has been received."""
        receipt = WebhookEvent(
            id=0,
            provider=notification.provider,
            event_id=notification.event_id,
            kind=notification.kind,
            reference=notification.reference,
        )
        receipt.validate()
        return receipt

    def _request_for(self, order: Order, transaction: Transaction) -> PaymentRequest:
        return PaymentRequest(
            reference=transaction.reference,
            amount=transaction.amount,
            currency=transaction.currency,
            email=order.contact_email,
            order_reference=order.reference,
        )

    async def _own_order(self, *, user_id: int, order_id: int) -> Order:
        order = await self._orders.get_by_id(order_id)
        if order is None or order.user_id != user_id:
            raise NotFoundError("Order not found")
        return order

    async def _own_transaction(
        self, *, user_id: int, reference: str
    ) -> Transaction:
        transaction = await self._transactions.get_by_reference(reference)
        if transaction is None:
            raise NotFoundError("Payment not found")
        # Ownership is derived from the order the payment belongs to.
        await self._own_order(user_id=user_id, order_id=transaction.order_id)
        return transaction
