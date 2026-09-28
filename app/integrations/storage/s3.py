"""The file-storage contract, spoken to S3-compatible object storage.

Everything Amazon-specific is confined here: the boto3 client and its
keyword-capitalised request shapes, its exception hierarchy, and the fact that a
bucket and a region have to be named before anything can be addressed. Anything
that speaks the S3 API can be used through this adapter, which is why an optional
endpoint is part of the configuration.

Two translations are worth naming:

* A caller's declared media type becomes the object's ``ContentType`` metadata,
  which is how these providers remember what a stored blob is.
* A successful write is reported by the contract as a key and nothing else. The
  S3 API replies to ``put_object`` with an ETag and no location: where an object
  is read back from (public bucket, signed access, CDN in front) is a property of
  the deployment rather than of the upload, so this adapter does not guess.

The SDK is blocking, so each call is offloaded with ``asyncio.to_thread`` -- the
event loop never waits on a transfer.
"""

from __future__ import annotations

import asyncio
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.integrations.storage.contract import (
    AbstractFileStorage,
    FileUpload,
    StoredFile,
)
from app.shared.exceptions import ProviderNotConfiguredError


class S3FileStorage(AbstractFileStorage):
    """Store objects in an S3-compatible bucket, in the contract's vocabulary."""

    provider = "s3"

    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        access_key_id: str = "",
        secret_access_key: str = "",
        endpoint_url: str = "",
        client: Any | None = None,
    ) -> None:
        # None of these can carry padding and still name anything real, and a
        # value read out of `.env` very often has exactly one space on the end.
        self._bucket = bucket.strip()
        self._region = region.strip()
        self._access_key_id = access_key_id.strip()
        self._secret_access_key = secret_access_key.strip()
        self._endpoint_url = endpoint_url.strip()
        # Injectable so the adapter can be tested without a network or an SDK
        # version dependency; production builds one client and keeps it.
        self._client = client

    async def upload(self, file: FileUpload) -> StoredFile:
        """Write one object and report what the provider said.

        An empty object is refused before the provider is called: it would store
        successfully and be indistinguishable from a failed upload afterwards.
        """
        file.validate()
        client = self._api()
        key = file.object_name
        params: dict[str, Any] = {"Bucket": self._bucket, "Key": key, "Body": file.content}
        if file.content_type:
            params["ContentType"] = file.content_type
        try:
            await asyncio.to_thread(client.put_object, **params)
        except (ClientError, BotoCoreError) as exc:
            # The provider's own vocabulary for "no": a bucket that does not
            # exist, credentials without write permission, a connection that
            # never opened. All of them are one thing to the caller.
            return StoredFile(success=False, message=_as_text(str(exc)))
        return StoredFile(success=True, key=key, message="File stored.")

    def _api(self) -> Any:
        """The S3 client for the configured bucket, built once and kept."""
        if self._client is not None:
            return self._client
        missing = self._missing_configuration()
        if missing:
            raise ProviderNotConfiguredError(
                "Storage provider 's3' is selected but "
                f"{' and '.join(missing)} {'are' if len(missing) > 1 else 'is'} not "
                "configured."
            )
        options: dict[str, Any] = {"region_name": self._region}
        if self._endpoint_url:
            options["endpoint_url"] = self._endpoint_url
        if self._access_key_id:
            options["aws_access_key_id"] = self._access_key_id
            options["aws_secret_access_key"] = self._secret_access_key
        self._client = boto3.client("s3", **options)
        return self._client

    def _missing_configuration(self) -> list[str]:
        """Which environment variables this deployment still lacks."""
        missing = [
            label
            for label, value in (("S3_BUCKET", self._bucket), ("S3_REGION", self._region))
            if not value
        ]
        # Half a key pair is not a credential: boto3 would sign nothing, or sign
        # wrongly, either of which reads as a provider problem downstream.
        if bool(self._access_key_id) != bool(self._secret_access_key):
            missing.append("S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY")
        return missing


def _as_text(value: str) -> str | None:
    return value.strip() or None
