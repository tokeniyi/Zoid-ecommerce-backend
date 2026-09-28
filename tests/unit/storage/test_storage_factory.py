"""Provider selection: configuration names a store, the table builds it.

Nothing here contacts a provider. What is under test is the one mapping that lets
``STORAGE_PROVIDER`` be changed without touching business logic -- and the promise
that a selection nobody recognises is stated as clearly as a missing key.
"""

from __future__ import annotations

from typing import Any

import pytest
from pytest import param

from app.config import Settings
from app.integrations.storage import (
    AbstractFileStorage,
    CloudinaryFileStorage,
    FileUpload,
    S3FileStorage,
    StoredFile,
    build_file_storage,
    supported_providers,
)
from app.integrations.storage.factory import _BUILDERS
from app.shared.exceptions import ProviderNotConfiguredError

#: Every storage credential, blanked. These tests prove selection and refusal and
#: must never reach a live provider because a developer keeps real keys in `.env`.
BLANKS: dict[str, str] = {
    "cloudinary_cloud_name": "",
    "cloudinary_api_key": "",
    "cloudinary_api_secret": "",
    "s3_bucket": "",
    "s3_region": "",
    "s3_endpoint_url": "",
    "s3_access_key_id": "",
    "s3_secret_access_key": "",
}

UPLOAD = FileUpload(filename="alpha-front.jpg", content=b"\xff\xd8jpeg bytes")


def _settings(**overrides: Any) -> Settings:
    return Settings(**{**BLANKS, **overrides})


class AnotherStore(AbstractFileStorage):
    """A second provider, existing only to be selected."""

    provider = "another"

    async def upload(self, file: FileUpload) -> StoredFile:
        return StoredFile(success=True, key=file.object_name)


# --- the table ----------------------------------------------------------------


def test_the_providers_a_deployment_may_choose_are_named() -> None:
    assert supported_providers() == ("cloudinary", "s3")


def test_the_supported_names_are_the_adapters_own_labels() -> None:
    """The registry cannot drift away from what the adapters actually claim."""
    assert set(supported_providers()) == {
        CloudinaryFileStorage.provider,
        S3FileStorage.provider,
    }


@pytest.mark.parametrize("name", supported_providers())
def test_every_advertised_provider_builds_a_store_that_claims_it(name: str) -> None:
    store = build_file_storage(_settings(storage_provider=name))

    assert isinstance(store, AbstractFileStorage)
    assert store.provider == name


def test_the_factory_offers_only_the_contract() -> None:
    """Callers get `AbstractFileStorage`; that is the whole point."""
    for name in supported_providers():
        assert isinstance(build_file_storage(_settings(storage_provider=name)), AbstractFileStorage)


@pytest.mark.parametrize(
    "configured",
    [
        param("cloudinary", id="exact"),
        param("CLOUDINARY", id="upper-case"),
        param("  s3  ", id="padded"),
        param("S3", id="upper-case-and-no-padding"),
    ],
)
def test_the_selection_is_not_fussy_about_spelling(configured: str) -> None:
    expected = {
        "cloudinary": CloudinaryFileStorage,
        "CLOUDINARY": CloudinaryFileStorage,
        "  s3  ": S3FileStorage,
        "S3": S3FileStorage,
    }[configured]

    assert isinstance(build_file_storage(_settings(storage_provider=configured)), expected)


def test_an_unrecognised_choice_is_refused_with_the_list_of_real_ones() -> None:
    with pytest.raises(ProviderNotConfiguredError) as refusal:
        build_file_storage(_settings(storage_provider="filing-cabinet"))

    assert "filing-cabinet" in str(refusal.value)
    assert "cloudinary" in str(refusal.value) and "s3" in str(refusal.value)


# --- selection is not validation ----------------------------------------------


@pytest.mark.parametrize("provider", sorted(supported_providers()))
async def test_a_store_can_be_built_before_its_credentials_exist(
    provider: str,
) -> None:
    """Building is what an application does at startup; storing is not.

    A deployment that has chosen a provider but not yet configured it must stay
    importable, and must say which environment variables it is missing the moment
    something actually needs to be kept. No request is ever sent to a provider
    that has not been configured for this deployment.
    """
    store = build_file_storage(_settings(storage_provider=provider))

    assert isinstance(store, AbstractFileStorage)
    with pytest.raises(ProviderNotConfiguredError):
        await store.upload(UPLOAD)


def test_another_provider_is_a_table_entry_not_a_rewiring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The replaceability the whole seam exists for, shown from the outside.

    Adding a provider means implementing the contract and listing it. Nothing that
    *stores* files is involved, which is why this test can add one without
    touching a service.
    """
    monkeypatch.setitem(_BUILDERS, AnotherStore.provider, lambda settings: AnotherStore())

    store = build_file_storage(_settings(storage_provider="another"))

    assert isinstance(store, AnotherStore)
    assert supported_providers() == ("cloudinary", "s3", AnotherStore.provider)
