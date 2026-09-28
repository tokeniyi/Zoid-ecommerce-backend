"""Concrete payment providers, plus the selection driven by configuration."""

from app.integrations.payments.factory import (
    build_payment_gateway,
    build_webhook_adapter,
    supported_providers,
)
from app.integrations.payments.paystack import PaystackPaymentGateway
from app.integrations.payments.stripe import StripePaymentGateway

__all__ = [
    "PaystackPaymentGateway",
    "StripePaymentGateway",
    "build_payment_gateway",
    "build_webhook_adapter",
    "supported_providers",
]
