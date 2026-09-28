"""The file-storage contract.

One seam between the application and *any* object store. It is expressed in a
single business capability -- keep this file -- and in normalised results, never
in provider payloads: what goes in is a name, some bytes and an optional media
type, not a Cloudinary option set or a boto3 ``put_object`` call. The adapters
(Cloudinary and S3-compatible storage today, selected by configuration) live
beside this module and translate in both directions.

Nothing here knows what a file is *for*. Whether bytes are a jersey photograph or
an exported spreadsheet is decided by the layer that owns the work; this contract
only accepts a thing to store and reports where the provider put it. That is what
lets the store be replaced without a line of business logic noticing.

No third-party import is allowed in this module: a contract that reaches for an
SDK stops being a seam.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.shared.exceptions import ValidationError


@dataclass(frozen=True)
class FileUpload:
    """One file to be stored, described the way any provider understands it.

    ``key`` is the name the caller wants the file kept under. It is optional
    because not every provider accepts one, and not every caller cares: when it
    is blank the stored name is the filename.
    """

    filename: str
    content: bytes
    content_type: str = ""
    key: str = ""

    @property
    def object_name(self) -> str:
        """The name to store under: the requested key, else the filename."""
        return self.key.strip() or self.filename.strip()

    def validate(self) -> None:
        """Reject what no provider could have stored correctly.

        Checked here, once, rather than in each adapter: an empty file and a name
        that escapes the store's own namespace are the same mistake wherever the
        bytes are going, and a provider that silently accepted the second would
        have written somewhere its operator did not intend.
        """
        if not self.content:
            raise ValidationError("File upload requires content")
        if not self.object_name:
            raise ValidationError("File upload requires a filename")
        parts = self.object_name.split("/")
        if self.object_name.startswith("/") or ".." in parts:
            raise ValidationError("File upload requires a name inside the store")


@dataclass(frozen=True)
class StoredFile:
    """Normalised outcome of asking a provider to keep one file.

    ``key`` is what the provider calls the object, which is not necessarily the
    name that went in: some providers file things under a name of their own.
    ``url`` is filled only when the provider reported a location of its own --
    an upload reply from S3-compatible storage carries no address, because where
    an object is read back from is a property of the deployment (bucket policy,
    CDN) rather than of the write.
    """

    success: bool
    key: str | None = None
    url: str | None = None
    message: str | None = None


class AbstractFileStorage(ABC):
    """The only storage capability the application is allowed to ask for."""

    #: Short, stable identifier of the implementation ("cloudinary", "s3").
    provider: str = "none"

    @abstractmethod
    async def upload(self, file: FileUpload) -> StoredFile:
        """Store one file and report what the provider said.

        A provider that refuses or cannot be reached is reported, not raised:
        the caller decides whether an unstored file is worth retrying or worth
        telling someone about. ``ProviderNotConfiguredError`` is the one
        exception -- selecting a provider without credentials is a deployment
        mistake that should not be swallowed.
        """
