"""The webhook contract: what a provider may tell us, and in whose words.

These are the same guarantees the gateway contract was written to give: the
application is handed business vocabulary, never a vendor's event names, and it
has no way to skip the signature check by accident.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from app.domains.payments.domain.entities import Refund, Transaction, WebhookEvent
from app.domains.payments.domain.enums import RefundStatus, WebhookKind
from app.domains.payments.domain.webhooks import (
    AbstractWebhookAdapter,
    WebhookNotification,
)
from app.shared.exceptions import ConflictError, ValidationError

PROVIDER_WORDS = ("paystack", "stripe", "charge", "intent", "sig", "hmac")


def _notification(**overrides: object) -> WebhookNotification:
    fields: dict[str, object] = {
        "provider": "fake",
        "event_id": "evt-1",
        "kind": WebhookKind.PAYMENT_PAID,
        "reference": "PAY-1",
    }
    fields.update(overrides)
    return WebhookNotification(**fields)  # type: ignore[arg-type]


def test_the_contract_asks_for_exactly_one_thing() -> None:
    """One entry point, so signature checking cannot be stepped around."""
    capabilities = {
        name
        for name in dir(AbstractWebhookAdapter)
        if not name.startswith("_")
        and callable(getattr(AbstractWebhookAdapter, name, None))
    }

    assert capabilities == {"parse_notification"}


def test_the_contract_cannot_be_implemented_by_accident() -> None:
    with pytest.raises(TypeError):
        AbstractWebhookAdapter()  # type: ignore[abstract]


@pytest.mark.parametrize(
    "reference", [None, ""], ids=("no-reference", "empty-reference")
)
def test_a_notification_that_does_not_name_our_payment_says_so(reference: str | None) -> None:
    assert _notification(reference=reference).names_our_payment is False
    assert _notification().names_our_payment is True


def test_the_notification_is_read_only_evidence() -> None:
    """The HTTP layer may hand this around, but nobody may edit the news."""
    notification = _notification()

    with pytest.raises(FrozenInstanceError):
        notification.kind = WebhookKind.IGNORED  # type: ignore[misc]


def test_the_vocabulary_carries_no_vendor_words() -> None:
    """``WebhookKind`` is this shop's language, not the provider's."""
    for kind in WebhookKind:
        lowered = kind.value.lower()
        assert not any(word in lowered for word in PROVIDER_WORDS), kind


def test_every_event_is_interpretable_or_explicitly_uninteresting() -> None:
    """There is no "we did not think about this event" answer."""
    assert set(WebhookKind) == {
        WebhookKind.PAYMENT_PAID,
        WebhookKind.PAYMENT_FAILED,
        WebhookKind.REFUND_SETTLED,
        WebhookKind.IGNORED,
    }


# --- recorded receipts --------------------------------------------------------


def test_a_receipt_knows_whether_it_was_acted_on() -> None:
    receipt = WebhookEvent(
        id=0, provider="fake", event_id="evt-1", kind=WebhookKind.PAYMENT_PAID
    )

    assert receipt.processed is False
    receipt.mark_processed(transaction_id=42)
    assert receipt.processed is True
    assert receipt.transaction_id == 42


def test_a_receipt_without_an_event_id_is_not_a_receipt() -> None:
    receipt = WebhookEvent(id=0, provider="fake", event_id="", kind=WebhookKind.IGNORED)

    with pytest.raises(ValidationError):
        receipt.validate()


# --- the refund ledger and what is left to give back --------------------------


def _transaction() -> Transaction:
    return Transaction(
        id=1,
        reference="PAY-1",
        order_id=10,
        amount=Decimal("100.00"),
        currency="NGN",
        provider="fake",
    )


def test_a_declined_refund_owes_nothing_to_the_ledger() -> None:
    refused = Refund(
        id=0,
        reference="RFD-1",
        transaction_id=1,
        amount=Decimal("10.00"),
        currency="NGN",
        provider="fake",
        status=RefundStatus.FAILED,
    )
    settled = Refund(
        id=0,
        reference="RFD-2",
        transaction_id=1,
        amount=Decimal("10.00"),
        currency="NGN",
        provider="fake",
        status=RefundStatus.SUCCEEDED,
    )

    assert refused.is_settled is False
    assert settled.is_settled is True


def test_a_refund_needs_a_positive_amount_of_a_real_currency() -> None:
    incomplete = Refund(
        id=0,
        reference="RFD-1",
        transaction_id=1,
        amount=Decimal("0"),
        currency="NGN",
        provider="fake",
    )

    with pytest.raises(ValidationError):
        incomplete.validate()


@pytest.mark.parametrize(
    "already_refunded",
    [Decimal("0.00"), Decimal("60.00")],
    ids=("none-yet", "partly"),
)
def test_a_payment_only_owes_what_is_left(already_refunded: Decimal) -> None:
    remaining = _transaction().refundable_amount(already_refunded)

    assert remaining == Decimal("100.00") - already_refunded


def test_a_fully_refunded_payment_owes_nothing_more() -> None:
    with pytest.raises(ConflictError):
        _transaction().refundable_amount(Decimal("100.00"))
