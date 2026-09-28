"""The file-storage contract, spoken to Cloudinary.

Everything Cloudinary-specific is confined here: its process-wide account
configuration, its ``public_id``/``unique_filename`` upload options, and its
exception hierarchy. The application sees ``FileUpload`` in and ``StoredFile``
out, exactly as it would for any other provider.

Two translations are worth naming, because they are the whole reason this module
exists:

* Cloudinary names stored assets "public ids" and derives the extension from the
  media it detected, so a requested name has its extension taken off and the
  invented suffix switched off -- otherwise the caller's chosen name is only a
  prefix of what comes back.
* The media type a caller declares is not Cloudinary's vocabulary: it classifies
  an upload by inspecting the bytes, so ``content_type`` is deliberately not
  forwarded. Providers that store bytes verbatim do use it.

Notes on two details that are easy to get wrong:

* The SDK is blocking, so the call is offloaded with ``asyncio.to_thread`` -- the
  event loop never waits on an upload.
* There is no client object to hold the account: the SDK reads one module-global
  configuration when it signs a request. The adapter therefore applies its own
  settings immediately before sending, which is the narrowest window in which the
  values can only be this adapter's.
"""

from __future__ import annotations

import asyncio
import io
import os
from collections.abc import Mapping
from typing import Any

import cloudinary
import cloudinary.uploader
from cloudinary.exceptions import Error as CloudinaryError

from app.integrations.storage.contract import (
    AbstractFileStorage,
    FileUpload,
    StoredFile,
)
from app.shared.exceptions import ProviderNotConfiguredError


class CloudinaryFileStorage(AbstractFileStorage):
    """Store files in a Cloudinary account, in the contract's vocabulary."""

    provider = "cloudinary"

    def __init__(
        self,
        *,
        cloud_name: str,
        api_key: str,
        api_secret: str,
        uploader: Any | None = None,
    ) -> None:
        # None of an account's three coordinates can carry padding and still name
        # anything real, and a value read out of `.env` very often has exactly one
        # space on the end.
        self._cloud_name = cloud_name.strip()
        self._api_key = api_key.strip()
        self._api_secret = api_secret.strip()
        # Injectable so the adapter can be tested without a network or an SDK
        # version dependency; production uses the SDK's own upload surface.
        self._uploader = uploader

    async def upload(self, file: FileUpload) -> StoredFile:
        """Hand one file to Cloudinary and report its answer.

        A file with nothing in it, or with a name that would leave the account's
        namespace, is refused before the provider is called -- there is nothing
        for Cloudinary to tell us that we did not already know.
        """
        file.validate()
        service = self._api()
        try:
            response = await asyncio.to_thread(
                service.upload, io.BytesIO(file.content), **self._options_for(file)
            )
        except CloudinaryError as exc:
            # Cloudinary's own vocabulary for "no": wrong key, over quota, an
            # unsupported format, a reply we could not read. All of them are one
            # thing to the caller -- these bytes are not stored.
            return StoredFile(success=False, message=_as_text(str(exc)))
        return StoredFile(
            success=True,
            key=_text_field(response, "public_id"),
            # The signed delivery URL is what an asset is actually read from.
            url=_text_field(response, "secure_url") or _text_field(response, "url"),
            message="File stored.",
        )

    def _options_for(self, file: FileUpload) -> dict[str, Any]:
        name = file.object_name
        # Cloudinary appends the extension it detected itself, and adds a unique
        # suffix unless told not to. Both would move the file away from the name
        # the caller asked for, which is the name the contract reports back.
        return {
            "public_id": os.path.splitext(name)[0],
            "unique_filename": False,
        }

    def _api(self) -> Any:
        """The Cloudinary upload surface, carrying the configured account."""
        if self._uploader is not None:
            return self._uploader
        if not (self._cloud_name and self._api_key and self._api_secret):
            raise ProviderNotConfiguredError(
                "Storage provider 'cloudinary' is selected but CLOUDINARY_CLOUD_NAME, "
                "CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET are not configured."
            )
        cloudinary.config(
            cloud_name=self._cloud_name,
            api_key=self._api_key,
            api_secret=self._api_secret,
        )
        return cloudinary.uploader


def _as_text(value: str) -> str | None:
    return value.strip() or None


def _text_field(response: Any, name: str) -> str | None:
    """One text field, from whichever shape came back.

    The SDK hands back the provider's JSON as a mapping; a test double may
    reasonably hand back a plain object. Absent is absent either way.
    """
    if isinstance(response, Mapping):
        value: Any = response.get(name)
    else:
        value = getattr(response, name, None)
    return _as_text(str(value)) if value is not None else None
