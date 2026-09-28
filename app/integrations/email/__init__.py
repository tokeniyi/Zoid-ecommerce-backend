"""Concrete email providers, plus the selection driven by configuration."""

from app.integrations.email.factory import (
    build_email_sender,
    supported_providers,
)
from app.integrations.email.resend import ResendEmailSender
from app.integrations.email.sender import (
    AbstractEmailSender,
    EmailDelivery,
    EmailMessage,
)

__all__ = [
    "AbstractEmailSender",
    "EmailDelivery",
    "EmailMessage",
    "ResendEmailSender",
    "build_email_sender",
    "supported_providers",
]
