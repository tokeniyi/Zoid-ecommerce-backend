"""The Resend adapter: what it hands the SDK, and what it makes of the answer.

The SDK's one entry point is injected as a double, so these tests pin the
*translation* -- the contract's message in, the contract's delivery report out --
without a network or a provider account. The exception is the credential test,
which uses the SDK's real entry point because holding the key correctly is the
SDK's own quirk rather than anything this adapter can be told to do.
"""

from __future__ import annotations

import threading
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
import resend
from pytest import param
from resend.exceptions import (
    MissingApiKeyError,
    NoContentError,
    RateLimitError,
    ResendError,
)

from app.integrations.email.resend import ResendEmailSender
from app.integrations.email.sender import EmailMessage
from app.shared.exceptions import (
    ProviderNotConfiguredError,
    ValidationError,
)

API_KEY = "re_test_key_at_the_adapter"
FROM = "Zoid <shop@zoid.example>"
MESSAGE = EmailMessage(
    to="owner@zoid.example",
    subject="Paid order ZD-ABC12345 - 42,000.00 NGN",
    text_body="Order ZD-ABC12345 has been paid.\n\nTotal  42,000.00 NGN",
)


class FakeResend:
    """``Emails.send(params)``, with the answer scripted by the test."""

    def __init__(
        self,
        *,
        response: Any = None,
        error: BaseException | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.threads: list[int] = []
        self.response = response if response is not None else {"id": "re_9"}
        self.error = error

    def send(self, params: dict[str, Any]) -> Any:
        self.calls.append(params)
        self.threads.append(threading.get_ident())
        if self.error is not None:
            raise self.error
        return self.response


def _sender(
    *,
    api_key: str = API_KEY,
    from_address: str = FROM,
    client: FakeResend | None = None,
) -> ResendEmailSender:
    return ResendEmailSender(
        api_key=api_key,
        from_address=from_address,
        client=client,
    )


# --- handing a message over ---------------------------------------------------


def test_the_adapter_labels_itself_for_the_provider_slot() -> None:
    assert ResendEmailSender.provider == "resend"


async def test_a_message_is_handed_over_as_a_message_and_nothing_more() -> None:
    """The provider learns that something must be sent, not that it is an order.

    Exact equality matters here: an adapter that started receiving order numbers,
    totals and line items would be the place e-commerce knowledge leaks to.
    """
    client = FakeResend()

    await _sender(client=client).send(MESSAGE)

    assert client.calls == [
        {
            "from": FROM,
            "to": MESSAGE.to,
            "subject": MESSAGE.subject,
            "text": MESSAGE.text_body,
        }
    ]


async def test_the_sending_account_comes_from_configuration() -> None:
    client = FakeResend()

    await _sender(from_address="Zoid <other@zoid.example>", client=client).send(MESSAGE)

    assert client.calls[0]["from"] == "Zoid <other@zoid.example>"


async def test_the_blocking_sdk_is_kept_off_the_event_loop() -> None:
    """Resend's call is synchronous, so it must not run on the loop's thread."""
    client = FakeResend()

    await _sender(client=client).send(MESSAGE)

    assert client.threads != [threading.get_ident()]


# --- what the provider's answer becomes ---------------------------------------


async def test_an_accepted_message_is_reported_with_its_provider_id() -> None:
    client = FakeResend(response={"id": "re_42", "http_headers": {"x": "1"}})

    delivery = await _sender(client=client).send(MESSAGE)

    assert delivery.success is True
    assert delivery.provider_message_id == "re_42"


async def test_a_message_can_be_accepted_without_an_id_coming_back() -> None:
    client = FakeResend(response={"id": ""})

    delivery = await _sender(client=client).send(MESSAGE)

    assert delivery.success is True
    assert delivery.provider_message_id is None


async def test_the_id_is_read_whichever_shape_the_reply_took() -> None:
    client = FakeResend(response=SimpleNamespace(id="re_object"))

    delivery = await _sender(client=client).send(MESSAGE)

    assert delivery.provider_message_id == "re_object"


@pytest.mark.parametrize(
    "error",
    [
        param(
            ResendError(
                code=422,
                error_type="validation_error",
                message="domain not verified",
                suggested_action="verify a domain",
            ),
            id="rejected-content",
        ),
        param(
            RateLimitError(
                message="too many requests",
                error_type="rate_limit_exceeded",
                code=429,
            ),
            id="over-quota",
        ),
        param(
            MissingApiKeyError(
                message="an API key is required",
                error_type="missing_api_key",
                code=401,
            ),
            id="bad-credentials",
        ),
        param(NoContentError(), id="empty-reply"),
    ],
)
async def test_every_way_resend_can_say_no_becomes_one_kind_of_answer(
    error: BaseException,
) -> None:
    """The SDK's hierarchy is not the application's problem.

    A refused message and a reply this adapter could not read are the same thing
    to a caller: this message did not go out, and here is what the provider said.
    """
    client = FakeResend(error=error)

    delivery = await _sender(client=client).send(MESSAGE)

    assert delivery.success is False
    assert delivery.provider_message_id is None
    assert delivery.message == str(error).strip()


async def test_a_provider_that_cannot_be_reached_is_still_just_a_failed_send() -> None:
    """The SDK wraps transport trouble as one of its own errors; it stays that."""
    client = FakeResend(
        error=ResendError(
            code=500,
            error_type="HttpClientError",
            message="Could not reach Resend.",
            suggested_action="try again",
        )
    )

    delivery = await _sender(client=client).send(MESSAGE)

    assert delivery.success is False
    assert "reach" in (delivery.message or "")


# --- what is refused before a provider is ever asked --------------------------


async def test_an_unconfigured_provider_refuses_to_send_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A selected provider with no key is a deployment mistake, said loudly.

    The one case the contract raises rather than reports: swallowing it would
    leave a store silently never notifying anybody.
    """
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(resend.Emails, "send", lambda **kwargs: calls.append(kwargs))

    with pytest.raises(ProviderNotConfiguredError):
        await _sender(api_key="").send(MESSAGE)

    assert calls == []


async def test_a_message_with_nowhere_to_go_is_refused_before_the_provider_is_asked(
) -> None:
    client = FakeResend()

    with pytest.raises(ValidationError):
        await _sender(client=client).send(replace(MESSAGE, to=""))

    assert client.calls == []


async def test_the_credential_reaches_the_sdk_that_needs_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resend has no client object: one module-global key is read per call.

    The SDK's own entry point is used here, with only its transport replaced,
    because *when* the key is set is exactly the thing a double could not catch.
    """
    seen: dict[str, Any] = {}

    def capture(params: dict[str, Any]) -> dict[str, str]:
        seen["api_key"] = resend.api_key
        seen["params"] = params
        return {"id": "re_from_the_sdk"}

    monkeypatch.setattr(resend, "api_key", None, raising=False)
    monkeypatch.setattr(resend.Emails, "send", staticmethod(capture))

    delivery = await _sender().send(MESSAGE)

    assert delivery.success is True
    assert delivery.provider_message_id == "re_from_the_sdk"
    assert seen["api_key"] == API_KEY
    assert seen["params"]["to"] == MESSAGE.to
