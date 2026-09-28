"""The email contract.

This is the single seam between the application and *any* email provider. It is
expressed in one business capability -- deliver this message -- and in normalised
results, never in provider payloads: what goes in is an address, a subject and a
body, not a Resend ``params`` dict or a SendGrid mail object. Adapters (Resend
today, SendGrid possibly later, selected by configuration) live beside this
module and translate in both directions.

Deliberately, nothing here knows what the message is *about*. The e-commerce
meaning of an order notification is worked out by the layer that owns the order;
this contract only says "send this" and reports what the provider answered. That
is why a provider can be swapped without a line of business logic noticing.

No third-party import is allowed in this module: a contract that reaches for an
SDK stops being a seam.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.shared.exceptions import ValidationError


def is_email_address(value: str) -> bool:
    """Whether ``value`` can be handed to a provider as one address.

    One rule, asked in two places: before composing a message ("is there anyone
    to notify?") and before sending one. A store that has not configured an
    owner address is a normal deployment state, not a send failure, so the
    question has to be answerable without constructing and rejecting a message.

    A comma is refused although it is legal in an address in theory: in practice
    it is how people write two recipients into one field, and this contract has
    one recipient per message.
    """
    stripped = value.strip()
    if not stripped or "@" not in stripped or "," in stripped:
        return False
    return not any(character.isspace() for character in stripped)


@dataclass(frozen=True)
class EmailMessage:
    """One message to be delivered, in terms any provider can send."""

    to: str
    subject: str
    text_body: str

    @property
    def has_recipient(self) -> bool:
        """Whether this message has anywhere to go."""
        return is_email_address(self.to)

    def validate(self) -> None:
        if not is_email_address(self.to):
            raise ValidationError("Email requires a valid recipient address")
        if not self.subject.strip():
            raise ValidationError("Email requires a subject")
        if not self.text_body.strip():
            raise ValidationError("Email requires a body")


@dataclass(frozen=True)
class EmailDelivery:
    """Normalised outcome of asking a provider to deliver one message.

    ``success`` answers "did the provider accept the message for delivery", not
    "did it reach an inbox" -- no provider promises the second, and an
    application that assumed it would be built on a guarantee it does not have.
    """

    success: bool
    provider_message_id: str | None = None
    message: str | None = None


class AbstractEmailSender(ABC):
    """The only email capability the application is allowed to ask for."""

    #: Short, stable identifier of the implementation ("resend").
    provider: str = "none"

    @abstractmethod
    async def send(self, message: EmailMessage) -> EmailDelivery:
        """Deliver one message and report what the provider said.

        A provider that cannot be reached is reported, not raised: the caller
        has already done the work it cares about and decides what to do about an
        undeliverable notification. ``ProviderNotConfiguredError`` is the one
        exception -- selecting a provider without credentials is a deployment
        mistake that should not be swallowed.
        """
