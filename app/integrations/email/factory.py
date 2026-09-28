"""Email provider selection.

Configuration names the provider; this module is the only place that maps that
name to a concrete sender. Everything above it receives the
``AbstractEmailSender`` contract, which is what lets ``EMAIL_PROVIDER`` be changed
without touching a line of business logic.

The table is the whole policy: add an adapter, list it here, configure it. A
second provider (SendGrid, say) is a new module implementing the same contract and
one new entry -- not a change to anything that sends mail.

As with payments, credentials are *not* checked here. An unconfigured deployment
stays importable and its sender fails loudly, as unconfigured, the first time a
message is actually tried.
"""

from __future__ import annotations

from collections.abc import Callable

from app.config import Settings, get_settings
from app.integrations.email.resend import ResendEmailSender
from app.integrations.email.sender import AbstractEmailSender
from app.shared.exceptions import ProviderNotConfiguredError


def _resend(settings: Settings) -> AbstractEmailSender:
    return ResendEmailSender(
        api_key=settings.resend_api_key,
        from_address=settings.email_from,
    )


#: provider name (as configured) -> sender builder
_BUILDERS: dict[str, Callable[[Settings], AbstractEmailSender]] = {
    ResendEmailSender.provider: _resend,
}


def supported_providers() -> tuple[str, ...]:
    """The provider names this deployment can be configured with."""
    return tuple(_BUILDERS)


def build_email_sender(settings: Settings | None = None) -> AbstractEmailSender:
    """The sender for the configured provider, as the contract."""
    config = settings if settings is not None else get_settings()
    provider = config.email_provider.strip().lower()
    builder: Callable[[Settings], AbstractEmailSender] | None = _BUILDERS.get(provider)
    if builder is None:
        raise ProviderNotConfiguredError(
            f"Unsupported email provider '{config.email_provider}'. "
            f"Configure one of: {', '.join(supported_providers())}."
        )
    return builder(config)
