"""Provider selection.

The point of the factory is that configuration -- not code -- decides which
provider is speaking, and that nothing above it can tell. The last test here is
the architecture rule as an executable check.
"""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

import pytest

from app import __file__ as app_file
from app.config import Settings, get_settings
from app.domains.orders.domain.entities import Order, OrderItem
from app.domains.payments.application.service import PaymentService
from app.domains.payments.domain.gateway import (
    AbstractPaymentGateway,
    PaymentInitiation,
    PaymentRequest,
    PaymentVerification,
    RefundRequest,
    RefundResult,
)
from app.domains.payments.domain.webhooks import AbstractWebhookAdapter
from app.integrations.payments import (
    PaystackPaymentGateway,
    StripePaymentGateway,
    build_payment_gateway,
    build_webhook_adapter,
    supported_providers,
)
from app.shared.exceptions import ProviderNotConfiguredError
from tests.unit.payments.test_payment_service import (
    InMemoryOrderRepository,
    InMemoryRefundRepository,
    InMemoryTransactionRepository,
    InMemoryWebhookEventRepository,
)


def _settings(provider: str) -> Settings:
    """The live configuration with the provider choice changed and keys blanked.

    Secrets are removed on purpose: these tests prove selection and refusal, and
    must never reach a live provider because a developer happens to keep real
    keys in their `.env`.
    """
    return get_settings().model_copy(
        update={
            "payment_provider": provider,
            "paystack_secret_key": "",
            "stripe_secret_key": "",
            "paystack_webhook_secret": "",
            "stripe_webhook_secret": "",
        }
    )


def _order() -> Order:
    return Order(
        id=10,
        reference="ZD-ABC12345",
        user_id=7,
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


# --- selection ----------------------------------------------------------------


def test_paystack_configuration_selects_the_paystack_adapter() -> None:
    gateway = build_payment_gateway(_settings("paystack"))

    assert isinstance(gateway, PaystackPaymentGateway)
    assert gateway.provider == "paystack"


def test_stripe_configuration_selects_the_stripe_adapter() -> None:
    gateway = build_payment_gateway(_settings("stripe"))

    assert isinstance(gateway, StripePaymentGateway)
    assert gateway.provider == "stripe"


@pytest.mark.parametrize("configured", ["Stripe", "  paystack  ", "PAYSTACK"])
def test_the_provider_name_is_matched_leniently(configured: str) -> None:
    expected = {
        "Stripe": StripePaymentGateway,
        "  paystack  ": PaystackPaymentGateway,
        "PAYSTACK": PaystackPaymentGateway,
    }[configured]

    assert isinstance(build_payment_gateway(_settings(configured)), expected)


def test_an_unsupported_provider_is_refused_by_name() -> None:
    with pytest.raises(ProviderNotConfiguredError) as refused:
        build_payment_gateway(_settings("mercury"))

    message = str(refused.value)
    assert "mercury" in message
    assert "paystack" in message and "stripe" in message


def test_the_supported_names_are_the_adapters_own_labels() -> None:
    """The registry cannot drift away from what the adapters actually claim."""
    assert set(supported_providers()) == {
        PaystackPaymentGateway.provider,
        StripePaymentGateway.provider,
    }


def test_the_factory_offers_only_the_contract() -> None:
    """Callers get `AbstractPaymentGateway`; that is the whole point."""
    for name in supported_providers():
        assert isinstance(build_payment_gateway(_settings(name)), AbstractPaymentGateway)


# --- the inbound half ---------------------------------------------------------


def test_every_selected_adapter_also_reads_its_provider_notifications() -> None:
    """Whichever provider is configured, its webhooks are understood.

    If an adapter ever ships without webhook intake, composition hands over
    ``None`` rather than a half-capable object -- this test is the tripwire that
    says whether that is about to happen.
    """
    for name in supported_providers():
        gateway = build_payment_gateway(_settings(name))
        assert isinstance(build_webhook_adapter(gateway), AbstractWebhookAdapter)


def test_the_webhook_adapter_is_the_same_conversation_as_the_gateway() -> None:
    """One provider, one adapter: the object answering us is the one talking back."""
    for name in supported_providers():
        gateway = build_payment_gateway(_settings(name))
        assert build_webhook_adapter(gateway) is gateway


def test_a_gateway_that_cannot_receive_notifications_is_reported_as_such() -> None:
    class DeafGateway(AbstractPaymentGateway):
        provider = "deaf"

        async def create_payment(self, request: PaymentRequest) -> PaymentInitiation:
            raise NotImplementedError

        async def verify_payment(self, reference: str) -> PaymentVerification:
            raise NotImplementedError

        async def refund_payment(self, request: RefundRequest) -> RefundResult:
            raise NotImplementedError

    assert build_webhook_adapter(DeafGateway()) is None


# --- the PASS condition -------------------------------------------------------


@pytest.mark.parametrize("provider", sorted(supported_providers()))
async def test_the_same_service_drives_whichever_adapter_is_selected(
    provider: str,
) -> None:
    """Changing PAYMENT_PROVIDER changes only the adapter.

    Same ``PaymentService`` class, same constructor call, same code path -- and,
    with no credentials configured, the same loud refusal. No request is ever
    sent to a provider that has not been configured for this deployment.
    """
    service = PaymentService(
        transactions=InMemoryTransactionRepository(),
        orders=InMemoryOrderRepository(_order()),
        refunds=InMemoryRefundRepository(),
        webhook_events=InMemoryWebhookEventRepository(),
        gateway=build_payment_gateway(_settings(provider)),
    )

    with pytest.raises(ProviderNotConfiguredError):
        await service.initiate(user_id=7, order_id=10)


#: Provider names, as the architecture's audit lists them. None of them may
#: appear in an import made by business code.
PROVIDER_NAMES = ("paystack", "stripe", "resend", "sendgrid", "cloudinary")

#: The contract modules the architecture itself places under ``integrations``.
#: The email interface lives there (architecture #30), so a domain may import
#: exactly that file -- and nothing else in the package.
CONTRACTS_IN_INTEGRATIONS = frozenset({"app.integrations.email.sender"})


def test_no_business_module_names_a_provider_or_reaches_into_integrations() -> None:
    """Domains speak contracts; the wiring lives outside them.

    A provider import inside ``app/domains`` -- or a hop into an adapter or into
    the factory that selects one -- would silently re-couple the business to one
    vendor.
    """
    domains = Path(app_file).parent / "domains"
    assert domains.is_dir()

    offenders: list[str] = []
    for module in sorted(domains.rglob("*.py")):
        for name in _imported_modules(module):
            lowered = name.lower()
            if any(provider in lowered for provider in PROVIDER_NAMES):
                offenders.append(f"{module}: imports {name}")
            elif name.startswith("app.integrations") and (
                name not in CONTRACTS_IN_INTEGRATIONS
            ):
                offenders.append(f"{module}: reaches into integrations")

    assert offenders == []


def _imported_modules(module: Path) -> list[str]:
    tree = ast.parse(module.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names
