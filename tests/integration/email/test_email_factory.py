"""Provider selection: configuration names a sender, the table builds it.

Nothing here contacts a provider. What is under test is the one mapping that lets
``EMAIL_PROVIDER`` be changed without touching business logic -- and the promise
that a selection nobody recognises is stated as clearly as a missing key.
"""

from __future__ import annotations

from typing import Any

import pytest
from pytest import param

from app.config import Settings
from app.integrations.email import build_email_sender, supported_providers
from app.integrations.email.factory import _BUILDERS
from app.integrations.email.resend import ResendEmailSender
from app.integrations.email.sender import (
    AbstractEmailSender,
    EmailDelivery,
    EmailMessage,
)
from app.shared.exceptions import ProviderNotConfiguredError


def _settings(**overrides: Any) -> Settings:
    return Settings(**overrides)


class AnotherSender(AbstractEmailSender):
    """A second provider, existing only to be selected."""

    provider = "another"

    async def send(self, message: EmailMessage) -> EmailDelivery:
        return EmailDelivery(success=True, provider_message_id="another-1")


# --- the table ----------------------------------------------------------------


def test_the_providers_a_deployment_may_choose_are_named() -> None:
    assert supported_providers() == ("resend",)


@pytest.mark.parametrize("name", supported_providers())
def test_every_advertised_provider_builds_a_sender_that_claims_it(name: str) -> None:
    sender = build_email_sender(_settings(email_provider=name))

    assert isinstance(sender, AbstractEmailSender)
    assert sender.provider == name


@pytest.mark.parametrize(
    "configured",
    [
        param("resend", id="exact"),
        param("RESEND", id="upper-case"),
        param("  resend  ", id="padded"),
    ],
)
def test_the_selection_is_not_fussy_about_spelling(configured: str) -> None:
    sender = build_email_sender(_settings(email_provider=configured))

    assert isinstance(sender, ResendEmailSender)


def test_an_unrecognised_choice_is_refused_with_the_list_of_real_ones() -> None:
    with pytest.raises(ProviderNotConfiguredError) as refusal:
        build_email_sender(_settings(email_provider="carrier-pigeon"))

    assert "carrier-pigeon" in str(refusal.value)
    assert "resend" in str(refusal.value)


async def test_selection_is_not_validation() -> None:
    """A sender can be built before its credentials exist; sending cannot.

    Building is what an application does at import and startup time. A provider
    that is merely unconfigured must not make the app unbuildable -- it must make
    the one message that needed it fail with a reason anybody can act on.
    """
    sender = build_email_sender(
        _settings(
            email_provider="resend",
            resend_api_key="",
            email_from="Zoid <zoid@example.com>",
        )
    )

    assert isinstance(sender, ResendEmailSender)
    with pytest.raises(ProviderNotConfiguredError):
        await sender.send(
            EmailMessage(
                to="owner@example.com", subject="Anything", text_body="Anything at all"
            )
        )


def test_another_provider_is_a_table_entry_not_a_rewiring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The replaceability the whole seam exists for, shown from the outside.

    Adding a provider means implementing the contract and listing it. Nothing
    that *uses* email is involved, which is why this test can add one without
    touching a service.
    """
    monkeypatch.setitem(
        _BUILDERS, AnotherSender.provider, lambda settings: AnotherSender()
    )

    sender = build_email_sender(_settings(email_provider="another"))

    assert isinstance(sender, AnotherSender)
    assert supported_providers() == ("resend", AnotherSender.provider)
