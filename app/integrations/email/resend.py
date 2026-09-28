"""The email contract, spoken to Resend.

Everything Resend-specific is confined here: its single process-wide API key, its
``from``/``to``/``text`` parameter names, and its exception hierarchy. The
application sees ``EmailMessage`` in and ``EmailDelivery`` out, exactly as it
would for any other provider.

Notes on two details that are easy to get wrong:

* The SDK is blocking, so the call is offloaded with ``asyncio.to_thread`` -- the
  event loop never waits on an HTTP round trip.
* There is no client object to hold a credential: the SDK reads one module-global
  key when it builds its headers. The adapter therefore sets it immediately
  before sending, which is the narrowest window in which the value can only be
  this adapter's.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any

import resend
from resend.exceptions import NoContentError, ResendError

from app.integrations.email.sender import (
    AbstractEmailSender,
    EmailDelivery,
    EmailMessage,
)
from app.shared.exceptions import ProviderNotConfiguredError


class ResendEmailSender(AbstractEmailSender):
    """Deliver messages through Resend, in the contract's vocabulary."""

    provider = "resend"

    def __init__(
        self,
        *,
        api_key: str,
        from_address: str,
        client: Any | None = None,
    ) -> None:
        self._api_key = api_key
        # Who the shop sends as is configuration, never something the message
        # builder has to know about.
        self._from_address = from_address
        # Injectable so the adapter can be tested without a network or an SDK
        # version dependency; production uses the SDK's own entry point.
        self._client = client

    async def send(self, message: EmailMessage) -> EmailDelivery:
        """Hand one message to Resend and report its answer.

        A message with nowhere to go is refused before the provider is called --
        there is nothing for Resend to tell us that we did not already know.
        """
        message.validate()
        try:
            response = await self._request(self._api().send, self._params_for(message))
        except (ResendError, NoContentError) as exc:
            # Resend's own vocabulary for "no": bad key, over quota, rejected
            # domain, or a reply we could not read. All of them are one thing to
            # the caller -- this message did not go out.
            return EmailDelivery(success=False, message=_as_text(str(exc)))
        return EmailDelivery(
            success=True,
            provider_message_id=_message_id(response),
            message="Message accepted for delivery.",
        )

    def _params_for(self, message: EmailMessage) -> dict[str, Any]:
        return {
            "from": self._from_address,
            "to": message.to,
            "subject": message.subject,
            "text": message.text_body,
        }

    async def _request(self, call: Callable[..., Any], params: dict[str, Any]) -> Any:
        """One SDK call, off the event loop."""
        return await asyncio.to_thread(call, params=params)

    def _api(self) -> Any:
        """The Resend service surface, carrying the configured credential."""
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ProviderNotConfiguredError(
                "Email provider 'resend' is selected but RESEND_API_KEY is not "
                "configured."
            )
        resend.api_key = self._api_key
        return resend.Emails


def _as_text(value: str) -> str | None:
    return value.strip() or None


def _message_id(response: Any) -> str | None:
    """The id Resend gives a sent message, from whichever shape came back.

    The SDK hands back a mapping and injects ``http_headers`` into it; a test
    double may reasonably hand back a plain object. Absent is absent either way.
    """
    if isinstance(response, Mapping):
        value: Any = response.get("id")
    else:
        value = getattr(response, "id", None)
    return _as_text(str(value)) if value is not None else None
