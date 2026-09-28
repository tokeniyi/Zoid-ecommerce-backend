"""The payment contract is provider-independent, and it stays that way.

These tests use no gateway but a hand-written fake. They pin three things the
architecture depends on:

* the gateway contract exposes business capabilities and normalised results;
* the transaction state machine has exactly one home;
* nothing in the payments package imports a provider SDK.
"""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

import pytest

import app.domains.payments as payments_package
from app.domains.payments.domain.entities import Transaction
from app.domains.payments.domain.enums import PaymentAction, PaymentStatus
from app.domains.payments.domain.gateway import (
    AbstractPaymentGateway,
    PaymentInitiation,
    PaymentRequest,
    RefundRequest,
)
from app.shared.exceptions import ConflictError, ValidationError

SDK_NAMES = ("paystack", "stripe", "httpx", "requests", "aiohttp")


def _imported_names() -> list[str]:
    """Every module imported anywhere inside the payments package."""
    root = Path(payments_package.__file__).parent
    names: list[str] = []
    for file in sorted(root.rglob("*.py")):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
    return names


@pytest.mark.parametrize("sdk", SDK_NAMES)
def test_payments_package_imports_no_provider_sdk(sdk: str) -> None:
    offenders = [name for name in _imported_names() if sdk in name.lower()]

    assert offenders == [], f"payments must not import {sdk!r}, found {offenders}"


def test_gateway_contract_is_business_shaped() -> None:
    capabilities = {
        name
        for name in dir(AbstractPaymentGateway)
        if not name.startswith("_")
        and callable(getattr(AbstractPaymentGateway, name, None))
    }

    assert capabilities == {"create_payment", "verify_payment", "refund_payment"}


def test_initiation_reports_a_redirect_without_naming_a_provider() -> None:
    initiation = PaymentInitiation(
        success=True,
        status=PaymentStatus.PENDING,
        transaction_reference="PAY-1",
        provider_reference="prov-1",
        checkout_url="https://provider.example/checkout",
        action=PaymentAction.REDIRECT,
    )

    next_action = initiation.next_action
    assert next_action is not None
    action, url = next_action
    assert action is PaymentAction.REDIRECT
    assert url == "https://provider.example/checkout"


def test_initiation_without_a_url_has_no_next_action() -> None:
    initiation = PaymentInitiation(success=False, status=PaymentStatus.FAILED)

    assert initiation.next_action is None


def _transaction(status: PaymentStatus = PaymentStatus.PENDING) -> Transaction:
    return Transaction(
        id=1,
        reference="PAY-1",
        order_id=10,
        amount=Decimal("42000.00"),
        currency="NGN",
        provider="fake",
        status=status,
    )


def test_pending_to_paid_to_refunded() -> None:
    transaction = _transaction()

    transaction.attach_initiation(provider_reference="prov-1", checkout_url="https://x")
    assert transaction.is_pending
    assert transaction.provider_reference == "prov-1"

    transaction.mark_paid("prov-1")
    assert transaction.is_paid
    assert transaction.checkout_url is None

    transaction.mark_refunded("rf-1")
    assert transaction.status is PaymentStatus.REFUNDED


def test_settling_twice_is_harmless() -> None:
    transaction = _transaction()

    transaction.mark_paid()
    transaction.mark_paid()

    assert transaction.status is PaymentStatus.PAID


def test_refunding_twice_is_harmless() -> None:
    transaction = _transaction()
    transaction.mark_paid()

    transaction.mark_refunded()
    transaction.mark_refunded()

    assert transaction.status is PaymentStatus.REFUNDED


@pytest.mark.parametrize(
    "attempt",
    [
        pytest.param(lambda t: t.mark_paid(), id="paid"),
        pytest.param(lambda t: t.mark_refunded(), id="refunded"),
        pytest.param(
            lambda t: t.attach_initiation(provider_reference="p", checkout_url=None),
            id="reinitiated",
        ),
    ],
)
def test_a_failed_attempt_is_never_resurrected(attempt) -> None:
    transaction = _transaction()
    transaction.mark_failed("declined")

    with pytest.raises(ConflictError):
        attempt(transaction)


def test_only_a_paid_transaction_can_be_refunded() -> None:
    with pytest.raises(ConflictError):
        _transaction().mark_refunded()


def test_a_paid_transaction_is_never_marked_failed() -> None:
    with pytest.raises(ConflictError):
        _transaction(PaymentStatus.PAID).mark_failed("late failure")


@pytest.mark.parametrize(
    "field, value",
    [
        ("reference", ""),
        ("order_id", None),
        ("amount", Decimal("0")),
        ("currency", "NAIRA"),
    ],
)
def test_transaction_validation_rejects_incomplete_records(field: str, value: object) -> None:
    transaction = _transaction()
    setattr(transaction, field, value)

    with pytest.raises(ValidationError):
        transaction.validate()


def test_payment_request_is_immutable_business_data() -> None:
    request = PaymentRequest(
        reference="PAY-1",
        amount=Decimal("100.00"),
        currency="NGN",
        email="buyer@example.com",
        order_reference="ZD-1",
    )

    assert request.metadata == {}
    with pytest.raises(AttributeError):
        request.reference = "PAY-2"  # type: ignore[misc]


def test_a_refund_without_an_amount_is_a_full_refund() -> None:
    assert RefundRequest(transaction_reference="PAY-1").amount is None
