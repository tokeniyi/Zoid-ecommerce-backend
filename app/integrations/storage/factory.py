"""Storage provider selection.

Configuration names the provider; this module is the only place that maps that
name to a concrete store. Everything above it receives the ``AbstractFileStorage``
contract, which is what lets ``STORAGE_PROVIDER`` be changed without touching a
line of business logic.

The table is the whole policy: add an adapter, list it here, configure it. A
third provider is a new module implementing the same contract and one new entry
-- not a change to anything that stores files.

As with payments and email, credentials are *not* checked here. An unconfigured
deployment stays importable and its store fails loudly, as unconfigured, the
first time bytes are actually tried.
"""

from __future__ import annotations

from collections.abc import Callable

from app.config import Settings, get_settings
from app.integrations.storage.cloudinary import CloudinaryFileStorage
from app.integrations.storage.contract import AbstractFileStorage
from app.integrations.storage.s3 import S3FileStorage
from app.shared.exceptions import ProviderNotConfiguredError


def _cloudinary(settings: Settings) -> AbstractFileStorage:
    return CloudinaryFileStorage(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
    )


def _s3(settings: Settings) -> AbstractFileStorage:
    return S3FileStorage(
        bucket=settings.s3_bucket,
        region=settings.s3_region,
        access_key_id=settings.s3_access_key_id,
        secret_access_key=settings.s3_secret_access_key,
        endpoint_url=settings.s3_endpoint_url,
    )


#: provider name (as configured) -> store builder
_BUILDERS: dict[str, Callable[[Settings], AbstractFileStorage]] = {
    CloudinaryFileStorage.provider: _cloudinary,
    S3FileStorage.provider: _s3,
}


def supported_providers() -> tuple[str, ...]:
    """The provider names this deployment can be configured with."""
    return tuple(_BUILDERS)


def build_file_storage(settings: Settings | None = None) -> AbstractFileStorage:
    """The store for the configured provider, as the contract."""
    config = settings if settings is not None else get_settings()
    provider = config.storage_provider.strip().lower()
    builder: Callable[[Settings], AbstractFileStorage] | None = _BUILDERS.get(provider)
    if builder is None:
        raise ProviderNotConfiguredError(
            f"Unsupported storage provider '{config.storage_provider}'. "
            f"Configure one of: {', '.join(supported_providers())}."
        )
    return builder(config)
