"""The provider-independent email contract, and the boundaries it draws.

Nothing here reaches a network or a provider: what is under test is the shape of
the seam itself -- what counts as a sendable message, what a sender promises, and
which imports the architecture forbids.

The structural tests at the bottom are the cheap, permanent version of the rule
"application code depends on the email capability, not on Resend". Behavioural
tests can only ever catch a violation in the path they exercise; an import is
visible all at once.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
from pytest import param

import app
from app.integrations.email.sender import (
    AbstractEmailSender,
    EmailDelivery,
    EmailMessage,
    is_email_address,
)
from app.shared.exceptions import ValidationError

_APP_ROOT = Path(app.__file__).parent
_EMAIL_PACKAGE = _APP_ROOT / "integrations" / "email"
_MESSAGE = EmailMessage(
    to="owner@example.com", subject="Paid order", text_body="Order ZD-1 is paid."
)


# --- what counts as an address ------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        param("owner@example.com", True, id="plain"),
        param("  owner@example.com  ", True, id="surrounded-by-space"),
        param("shop.owner+orders@zoid.example", True, id="plus-tagging"),
        param("", False, id="empty"),
        param("   ", False, id="only-space"),
        param("owner(at)example.com", False, id="no-at-sign"),
        param("ada@example.com,owner@example.com", False, id="two-recipients-in-one-field"),
        param("me @example.com", False, id="space-inside"),
        param("newline@example.com\nforwarder@elsewhere.example", False, id="folded"),
    ],
)
def test_address_rule(value: str, expected: bool) -> None:
    assert is_email_address(value) is expected


def test_a_message_knows_whether_it_has_anywhere_to_go() -> None:
    assert _MESSAGE.has_recipient is True
    assert EmailMessage(to="", subject="s", text_body="b").has_recipient is False


# --- what counts as a sendable message ---------------------------------------


def test_a_complete_message_is_accepted() -> None:
    _MESSAGE.validate()


@pytest.mark.parametrize(
    "overrides",
    [
        param({"to": ""}, id="no-recipient"),
        param({"to": "not-an-address"}, id="recipient-is-not-an-address"),
        param({"subject": ""}, id="no-subject"),
        param({"subject": "   "}, id="blank-subject"),
        param({"text_body": ""}, id="no-body"),
        param({"text_body": "\n  \n"}, id="blank-body"),
    ],
)
def test_an_incomplete_message_is_refused(overrides: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        replace(_MESSAGE, **overrides).validate()


def test_a_message_cannot_be_rewritten_after_it_is_sent_off() -> None:
    """Providers are handed a message, so what they were handed must not move."""
    with pytest.raises(FrozenInstanceError):
        _MESSAGE.subject = "something else"  # type: ignore[misc]


def test_a_delivery_reports_acceptance_without_promising_inboxes() -> None:
    refused = EmailDelivery(success=False, message="domain not verified")
    accepted = EmailDelivery(success=True, provider_message_id="re_1")

    assert refused.success is False
    assert refused.provider_message_id is None
    assert accepted.success is True
    assert accepted.provider_message_id == "re_1"


# --- the sender interface -----------------------------------------------------


def test_the_contract_names_one_capability_and_no_provider() -> None:
    assert {name for name in dir(AbstractEmailSender) if not name.startswith("_")} == {
        "provider",
        "send",
    }
    assert AbstractEmailSender.provider == "none"


def test_a_sender_that_cannot_send_is_not_a_sender() -> None:
    class HalfBuilt(AbstractEmailSender):
        pass

    with pytest.raises(TypeError):
        HalfBuilt()  # type: ignore[abstract]


async def test_a_conforming_sender_needs_only_to_answer_send() -> None:
    class Minimal(AbstractEmailSender):
        async def send(self, message: EmailMessage) -> EmailDelivery:
            return EmailDelivery(success=True, provider_message_id=message.subject)

    delivery = await Minimal().send(_MESSAGE)

    assert delivery.provider_message_id == "Paid order"


# --- the boundaries the architecture draws ------------------------------------


def _imported_modules(path: Path) -> set[str]:
    """Every module a file names in an import, in absolute form."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


def _outside_email_package(path: Path) -> bool:
    return not path.is_relative_to(_EMAIL_PACKAGE)


def test_the_contract_itself_reaches_no_third_party_code() -> None:
    """A contract that imports an SDK has stopped being a seam."""
    imports = _imported_modules(_EMAIL_PACKAGE / "sender.py")
    roots = {name.split(".", 1)[0] for name in imports}

    assert roots - set(sys.stdlib_module_names) == {"app"}


def test_the_resend_sdk_is_reachable_only_from_its_adapter() -> None:
    offenders = [
        path.relative_to(_APP_ROOT).as_posix()
        for path in _APP_ROOT.rglob("*.py")
        if _outside_email_package(path)
        and any(name.split(".", 1)[0] == "resend" for name in _imported_modules(path))
    ]

    assert offenders == []


def test_business_code_that_wants_email_wants_the_contract() -> None:
    """Anything in the domains reaching into the email package must want ``sender``.

    The factory and the adapters are composition and provider detail; a domain
    importing either is a provider leaking into business logic.
    """
    reached = {
        name
        for path in (_APP_ROOT / "domains").rglob("*.py")
        for name in _imported_modules(path)
        if name.startswith("app.integrations.email")
    }

    assert reached == {"app.integrations.email.sender"}
