"""The webhook contract: how a provider reports what happened on its side.

``create_payment``/``verify_payment``/``refund_payment`` are the questions *we*
ask. A notification is the news a provider offers unprompted, which is why it
gets its own seam and its own rules:

* Verifying the provider's signature is not a step a caller can forget. It
  happens inside :meth:`AbstractWebhookAdapter.parse_notification`, which raises
  ``SignatureVerificationError`` rather than handing out an event nobody
  authenticated.
* What comes out is business vocabulary (paid / failed / refund settled /
  nothing of ours), never ``charge.succeeded`` or ``successful``.
* The provider's own event id is carried through, because that is the handle the
  application uses to recognise a redelivery.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from app.domains.payments.domain.enums import WebhookKind


@dataclass(frozen=True)
class WebhookNotification:
    """One provider event, in this application's vocabulary."""

    provider: str
    event_id: str
    kind: WebhookKind
    reference: str | None = None
    provider_reference: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    message: str | None = None

    @property
    def names_our_payment(self) -> bool:
        """Does this tell us about a payment this store started?"""
        return bool(self.reference)


class AbstractWebhookAdapter(ABC):
    """The provider-specific half of webhook intake."""

    #: Must match the gateway implementation of the same provider.
    provider: str = "none"

    @abstractmethod
    def parse_notification(
        self, *, payload: bytes, headers: Mapping[str, str]
    ) -> WebhookNotification:
        """Verify the signature on ``payload`` and normalise the event.

        ``headers`` are the request's, lower-cased: each adapter reads its own
        signature header and knows its own encoding, so no HTTP layer has to
        learn that a Paystack signature is not a Stripe one.

        Raises ``SignatureVerificationError`` when the payload is not
        authentically from the provider.
        """
