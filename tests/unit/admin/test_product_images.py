"""Product image uploads: what is accepted, and what the store is told."""

from __future__ import annotations

import pytest

from app.domains.admin.application.images import (
    ProductImageService,
    sniff_image,
    validate_image,
)
from app.integrations.storage.contract import AbstractFileStorage, FileUpload, StoredFile
from app.shared.exceptions import ProviderError, ValidationError

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
GIF = b"GIF89a" + b"\x00" * 32
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 32


class RecordingStore(AbstractFileStorage):
    provider = "recording"

    def __init__(self, reply: StoredFile | None = None) -> None:
        self.uploads: list[FileUpload] = []
        self._reply = reply

    async def upload(self, file: FileUpload) -> StoredFile:
        self.uploads.append(file)
        return self._reply or StoredFile(success=True, key=file.key, message="stored")


@pytest.mark.parametrize(
    ("content", "content_type", "extension"),
    [(JPEG, "image/jpeg", "jpg"), (PNG, "image/png", "png"),
     (GIF, "image/gif", "gif"), (WEBP, "image/webp", "webp")],
)
def test_images_are_recognised_by_their_bytes(
    content: bytes, content_type: str, extension: str
) -> None:
    kind = sniff_image(content)
    assert kind is not None
    assert (kind.content_type, kind.extension) == (content_type, extension)


@pytest.mark.parametrize(
    "content",
    [
        b"<html><script>alert(1)</script></html>",          # a page renamed shirt.jpg
        b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"/>',  # SVG can carry script
        b"%PDF-1.7 not an image",
        b"RIFF\x24\x00\x00\x00WAVEfmt ",                    # RIFF, but audio not WebP
        b"MZ\x90\x00 an executable",
        b"plain text",
    ],
)
def test_anything_else_is_refused_whatever_it_is_called(content: bytes) -> None:
    assert sniff_image(content) is None
    with pytest.raises(ValidationError, match="JPEG, PNG, GIF and WebP"):
        validate_image(content, max_bytes=1_000_000)


def test_empty_and_oversized_uploads_are_refused() -> None:
    with pytest.raises(ValidationError, match="empty"):
        validate_image(b"", max_bytes=100)
    with pytest.raises(ValidationError, match="too large"):
        validate_image(JPEG + b"\x00" * 100, max_bytes=100)
    assert validate_image(JPEG, max_bytes=len(JPEG)).kind.extension == "jpg"  # at the limit


def test_the_stored_name_is_generated_never_chosen_by_the_client() -> None:
    first = validate_image(PNG, max_bytes=1000)
    second = validate_image(PNG, max_bytes=1000)

    assert first.key.startswith("products/") and first.key.endswith(".png")
    assert first.key != second.key  # an upload cannot overwrite another image


async def test_the_store_is_told_what_the_file_really_is() -> None:
    store = RecordingStore()
    service = ProductImageService(storage=store, public_base_url="https://cdn.example.org/")

    uploaded = await service.upload(WEBP)

    sent = store.uploads[0]
    assert sent.content == WEBP and sent.content_type == "image/webp"
    assert sent.key == uploaded.key and uploaded.key.endswith(".webp")
    assert uploaded.url == f"https://cdn.example.org/{uploaded.key}"  # no double slash
    assert (uploaded.content_type, uploaded.size) == ("image/webp", len(WEBP))


async def test_a_providers_own_address_wins_over_the_configured_base() -> None:
    store = RecordingStore(
        StoredFile(success=True, key="cloud/abc", url="https://res.cloudinary.example/abc.jpg")
    )
    uploaded = await ProductImageService(storage=store, public_base_url="https://x").upload(JPEG)
    assert (uploaded.url, uploaded.key) == ("https://res.cloudinary.example/abc.jpg", "cloud/abc")


async def test_a_refused_upload_is_a_provider_error_with_the_providers_reason() -> None:
    store = RecordingStore(StoredFile(success=False, message="bucket does not exist"))
    with pytest.raises(ProviderError, match="bucket does not exist"):
        await ProductImageService(storage=store, public_base_url="https://x").upload(JPEG)


async def test_a_stored_image_nobody_can_reach_is_reported_not_returned() -> None:
    """S3 reports no address; without a configured base the URL would be a guess."""
    with pytest.raises(ProviderError, match="STORAGE_PUBLIC_BASE_URL"):
        await ProductImageService(storage=RecordingStore()).upload(JPEG)


async def test_a_bad_file_never_reaches_the_store() -> None:
    store = RecordingStore()
    service = ProductImageService(storage=store, public_base_url="https://x")
    with pytest.raises(ValidationError):
        await service.upload(b"not an image")
    assert store.uploads == []
