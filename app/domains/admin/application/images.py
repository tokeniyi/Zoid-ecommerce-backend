"""Product image uploads: what may be stored, and under what name.

Pure rules, so they are tested without a store. Two decisions matter:

* **The file decides what it is, not the client.** The type is read from the first
  bytes (a JPEG/PNG/GIF/WebP signature); the ``Content-Type`` the browser claimed
  and the filename it gave are ignored. An HTML page renamed ``shirt.jpg`` is
  refused. SVG is refused too: it is a document that can carry script, and a
  product photo does not need to be one.
* **The shop names the file, not the client.** The stored key is generated here,
  so an upload cannot choose a path, overwrite another image or guess a URL.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.integrations.storage.contract import AbstractFileStorage, FileUpload
from app.shared.exceptions import ProviderError, ValidationError

#: (signature prefix, content type, extension). WebP is checked separately: a RIFF
#: container whose form type is WEBP.
_SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"GIF87a", "image/gif", "gif"),
    (b"GIF89a", "image/gif", "gif"),
)

KEY_PREFIX = "products"


@dataclass(frozen=True)
class ImageKind:
    content_type: str
    extension: str


def sniff_image(content: bytes) -> ImageKind | None:
    """What image ``content`` actually is, or ``None`` if it is not an accepted one."""
    for signature, content_type, extension in _SIGNATURES:
        if content.startswith(signature):
            return ImageKind(content_type, extension)
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ImageKind("image/webp", "webp")
    return None


@dataclass(frozen=True)
class ValidImage:
    content: bytes
    kind: ImageKind
    #: The name the file will be stored under; generated, never client-chosen.
    key: str


def validate_image(content: bytes, *, max_bytes: int) -> ValidImage:
    """Accept ``content`` as a product image, or say why not."""
    if not content:
        raise ValidationError("The upload is empty.")
    if len(content) > max_bytes:
        raise ValidationError(
            f"The image is too large ({len(content)} bytes); the limit is {max_bytes} bytes."
        )
    kind = sniff_image(content)
    if kind is None:
        raise ValidationError("Only JPEG, PNG, GIF and WebP images can be uploaded.")
    key = f"{KEY_PREFIX}/{uuid4().hex}.{kind.extension}"
    return ValidImage(content=content, kind=kind, key=key)


@dataclass(frozen=True)
class UploadedImage:
    """A product image now in the store, with the address shoppers' browsers use."""

    url: str
    key: str
    content_type: str
    size: int


class ProductImageService:
    """Keeps product images in the configured file store.

    Separate from :class:`~app.domains.admin.application.service.AdminService` on
    purpose: that service is handed persistence contracts and nothing else, while
    this one is handed the storage contract. Neither learns which provider is
    behind it.
    """

    def __init__(
        self,
        *,
        storage: AbstractFileStorage,
        public_base_url: str = "",
        max_bytes: int = 5_000_000,
    ) -> None:
        self._storage = storage
        self._public_base_url = public_base_url.strip().rstrip("/")
        self._max_bytes = max_bytes

    async def upload(self, content: bytes) -> UploadedImage:
        """Keep an image and return its public address.

        The product then records that address (when it is created, in ``images``),
        so the catalog holds stable public URLs and never the bytes. An address
        typed in directly still works for images that are already hosted.
        """
        image = validate_image(content, max_bytes=self._max_bytes)
        stored = await self._storage.upload(
            FileUpload(
                filename=image.key,
                content=image.content,
                content_type=image.kind.content_type,
                key=image.key,
            )
        )
        if not stored.success:
            raise ProviderError(stored.message or "The image could not be stored.")
        key = stored.key or image.key
        url = stored.url or (f"{self._public_base_url}/{key}" if self._public_base_url else "")
        if not url:
            # Stored, but nobody can be told where to fetch it from.
            raise ProviderError(
                "The image was stored but its public address is unknown; "
                "set STORAGE_PUBLIC_BASE_URL for this storage provider."
            )
        return UploadedImage(
            url=url, key=key, content_type=image.kind.content_type, size=len(content)
        )
