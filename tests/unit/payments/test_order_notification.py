"""The store-owner notification: what it must contain, and how far it can fail.

Two halves, deliberately tested apart:

* :func:`build_order_notification` is pure composition -- an order and a payment
  in, one e-mail message out. Everything the architecture requires a shop owner
  to see has to be readable from the text, and the message must be one that any
  email provider can be asked to send.
* :class:`PaidOrderNotifier` decides *whether* to say it and reports what came
  back. It is the layer that must never turn a confirmed payment into a failed
  request, whatever email does.

The fake sender implements the contract, so nothing in here is provider code: the
tests would read exactly the same for a provider that does not exist yet.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pytest import param

from app.domains.orders.domain.entities import Order, OrderItem
from app.domains.orders.domain.enums import OrderStatus
from app.domains.payments.application.notifications import (
    PaidOrderNotifier,
    build_order_notification,
)
from app.domains.payments.domain.entities import Transaction
from app.domains.payments.domain.enums import PaymentStatus
from app.integrations.email.sender import (
    AbstractEmailSender,
    EmailDelivery,
    EmailMessage,
)
from app.shared.exceptions import ProviderNotConfiguredError

OWNER = "owner@zoid.example"
ORDER_REFERENCE = "ZD-ABC12345"
PAYMENT_REFERENCE = "PAY-AAAA1111"


class RecordingSender(AbstractEmailSender):
    """The email contract, with its answers scripted by the test."""

    provider = "recording"

    def __init__(
        self,
        *,
        delivery: EmailDelivery | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.calls: list[EmailMessage] = []
        self.delivery = delivery or EmailDelivery(
            success=True, provider_message_id="note-1"
        )
        self.error = error

    async def send(self, message: EmailMessage) -> EmailDelivery:
        self.calls.append(message)
        if self.error is not None:
            raise self.error
        return self.delivery


def _order(*, notes: str | None = "Leave with the guard") -> Order:
    return Order(
        id=10,
        reference=ORDER_REFERENCE,
        user_id=7,
        status=OrderStatus.PAID,
        currency="NGN",
        contact_name="Ada Zoid",
        contact_email="ada@example.com",
        contact_phone="+234 800 000 0000",
        address_line="12 Concrete Road",
        city_state="Lagos State",
        notes=notes,
        items=[
            OrderItem(
                id=1,
                variant_id=11,
                product_slug="alpha-home",
                product_name="Alpha Jersey",
                size="M",
                quantity=2,
                unit_price=Decimal("21000.00"),
            ),
            OrderItem(
                id=2,
                variant_id=12,
                product_slug="beta-away",
                product_name="Beta Jersey",
                size="L",
                quantity=1,
                unit_price=Decimal("18500.50"),
            ),
        ],
    )


def _payment() -> Transaction:
    return Transaction(
        id=500,
        reference=PAYMENT_REFERENCE,
        order_id=10,
        amount=Decimal("60500.50"),
        currency="NGN",
        provider="fake",
        status=PaymentStatus.PAID,
        provider_reference="prov-77",
    )


def _notification(
    *, owner: str = OWNER, notes: str | None = "Leave with the guard"
) -> EmailMessage:
    return build_order_notification(
        _order(notes=notes), _payment(), owner_email=owner
    )


# --- what the email has to say ------------------------------------------------


@pytest.mark.parametrize(
    "fragment",
    [
        param(ORDER_REFERENCE, id="order-number"),
        param("Ada Zoid", id="customer-name"),
        param("ada@example.com", id="customer-email"),
        param("+234 800 000 0000", id="customer-phone"),
        param("Alpha Jersey", id="product"),
        param("2 x Alpha Jersey", id="quantity"),
        param("size M", id="size"),
        param("21,000.00 NGN", id="unit-price"),
        param("18,500.50 NGN", id="odd-unit-price-is-not-rounded-away"),
        param("60,500.50 NGN", id="total"),
        param("12 Concrete Road", id="delivery-address"),
        param("Lagos State", id="delivery-city"),
        param("Leave with the guard", id="delivery-notes"),
        param(PAYMENT_REFERENCE, id="payment-reference"),
        param("prov-77", id="provider-reference"),
    ],
)
def test_a_paid_order_is_described_completely_enough_to_act_on(fragment: str) -> None:
    """Every datum the architecture lists for the owner's email is readable here."""
    assert fragment in _notification().text_body


def test_the_owner_addressed_the_message_to_somebody() -> None:
    message = _notification()

    assert message.to == OWNER
    assert message.has_recipient is True
    message.validate()


def test_the_subject_carries_the_order_being_announced() -> None:
    message = _notification()

    assert ORDER_REFERENCE in message.subject
    assert "60,500.50 NGN" in message.subject


def test_nothing_about_an_order_needs_html_to_be_read() -> None:
    """Plain text is the one thing every provider can be asked to send."""
    body = _notification().text_body

    assert "<" not in body and "&amp;" not in body


def test_optional_order_details_are_said_absent_rather_than_dropped() -> None:
    message = _notification(notes="")

    assert "Notes: none" in message.text_body
    assert "Leave with the guard" not in message.text_body


# --- whether it is sent -------------------------------------------------------


async def test_a_paid_order_is_announced_through_the_email_contract() -> None:
    sender = RecordingSender()

    notified = await PaidOrderNotifier(sender=sender, owner_email=OWNER).notify_paid(
        order=_order(), transaction=_payment()
    )

    assert notified is True
    assert len(sender.calls) == 1
    assert sender.calls[0].to == OWNER
    assert ORDER_REFERENCE in sender.calls[0].text_body


@pytest.mark.parametrize(
    "owner_email",
    [
        param("", id="not-configured"),
        param("   ", id="only-space"),
        param("shop-owner(at)zoid.example", id="not-an-address"),
    ],
)
async def test_a_store_with_nobody_to_tell_sends_nothing(owner_email: str) -> None:
    """An unconfigured recipient is a deployment choice, not a failed payment."""
    sender = RecordingSender()
    notifier = PaidOrderNotifier(sender=sender, owner_email=owner_email)

    notified = await notifier.notify_paid(order=_order(), transaction=_payment())

    assert notified is False
    assert sender.calls == []


@pytest.mark.parametrize(
    ("delivery", "error"),
    [
        param(
            EmailDelivery(success=False, message="domain not verified"),
            None,
            id="refused",
        ),
        param(EmailDelivery(success=False), None, id="refused-without-a-reason"),
        param(None, ProviderNotConfiguredError("no key"), id="unconfigured-provider"),
        param(None, RuntimeError("the provider exploded"), id="exploding-provider"),
    ],
)
async def test_no_email_problem_is_allowed_to_unpay_an_order(
    delivery: EmailDelivery | None, error: BaseException | None
) -> None:
    """The payment is already confirmed; notification is allowed to fail loudly.

    Reported as "nobody was told" and nothing more: an exception escaping here
    would roll back the settlement that paid the order.
    """
    sender = RecordingSender(delivery=delivery, error=error)

    notified = await PaidOrderNotifier(sender=sender, owner_email=OWNER).notify_paid(
        order=_order(), transaction=_payment()
    )

    assert notified is False
    assert len(sender.calls) == 1


async def test_the_notifier_renders_the_provider_it_was_given() -> None:
    """Which provider is happening is composition's business, not the payment's."""
    notifier = PaidOrderNotifier(sender=RecordingSender(), owner_email=OWNER)

    assert notifier.provider == "recording"
