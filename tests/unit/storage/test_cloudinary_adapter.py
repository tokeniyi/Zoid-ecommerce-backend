"""The Cloudinary adapter: what it hands the SDK, and what it makes of the answer.

The SDK's upload surface is injected as a double, so these tests pin the
*translation* -- contract file in, contract receipt out -- without a network or a
Cloudinary account. The exception is the credential test, which uses the SDK's
real entry point because carrying the account correctly is the SDK's own quirk
rather than anything this adapter can be told to do.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import cloudinary
import cloudinary.uploader
import pytest
from cloudinary.exceptions import (
    AuthorizationRequired,
    BadRequest,
    GeneralError,
    NotFound,
    RateLimited,
)
from cloudinary.exceptions import (
    Error as CloudinaryError,
)
from pytest import param

from app.integrations.storage.cloudinary import CloudinaryFileStorage
from app.integrations.storage.contract import FileUpload
from app.shared.exceptions import ProviderNotConfiguredError, ValidationError

ACCOUNT = {
    "cloud_name": "zoid-media",
    "api_key": "123456789012345",
    "api_secret": "a-secret-that-is-not-the-real-one",
}
UPLOAD = FileUpload(
    filename="alpha-front.jpg",
    content=b"\xff\xd8jpeg bytes\xff\xd9",
    content_type="image/jpeg",
)
RECEIPT = {"public_id": "alpha-front", "secure_url": "https://res.zoid.example/alpha.jpg"}


class FakeCloudinary:
    """``uploader.upload(file, **options)``, with the answer scripted by the test."""

    def __init__(self, *, response: Any = None, error: BaseException | None = None) -> None:
        self.calls: list[tuple[bytes, dict[str, Any]]] = []
        self.threads: list[int] = []
        self.response = response if response is not None else RECEIPT
        self.error = error

    def upload(self, file: Any, **options: Any) -> Any:
        self.calls.append((file.read(), options))
        self.threads.append(threading.get_ident())
        if self.error is not None:
            raise self.error
        return self.response


def _store(
    *,
    cloud_name: str = ACCOUNT["cloud_name"],
    api_key: str = ACCOUNT["api_key"],
    api_secret: str = ACCOUNT["api_secret"],
    uploader: FakeCloudinary | None = None,
) -> CloudinaryFileStorage:
    return CloudinaryFileStorage(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        uploader=uploader,
    )


# --- handing a file over ------------------------------------------------------


def test_the_adapter_labels_itself_for_the_provider_slot() -> None:
    assert CloudinaryFileStorage.provider == "cloudinary"


async def test_the_bytes_are_handed_over_as_a_file() -> None:
    uploader = FakeCloudinary()

    await _store(uploader=uploader).upload(UPLOAD)

    assert uploader.calls[0][0] == UPLOAD.content


async def test_a_requested_name_becomes_the_public_id_without_its_extension() -> None:
    """Exact equality matters here.

    Cloudinary adds the extension it detected and a unique suffix of its own; an
    adapter that let either through would hand back a name nobody asked for. And
    nothing e-commerce-shaped belongs in an upload request, which is what the
    pinned dictionary also proves.
    """
    uploader = FakeCloudinary()

    await _store(uploader=uploader).upload(UPLOAD)

    assert uploader.calls[0][1] == {"public_id": "alpha-front", "unique_filename": False}


async def test_a_namespace_in_the_name_is_kept() -> None:
    uploader = FakeCloudinary()

    await _store(uploader=uploader).upload(FileUpload(filename="jerseys/club/a.jpg", content=b"x"))

    assert uploader.calls[0][1]["public_id"] == "jerseys/club/a"


async def test_the_declared_media_type_is_left_to_the_provider_to_work_out() -> None:
    """Cloudinary classifies by inspecting bytes; forwarding a label would lie."""
    uploader = FakeCloudinary()

    await _store(uploader=uploader).upload(UPLOAD)

    assert "content_type" not in uploader.calls[0][1]


async def test_the_blocking_sdk_is_kept_off_the_event_loop() -> None:
    """Cloudinary's call is synchronous, so it must not run on the loop's thread."""
    uploader = FakeCloudinary()

    await _store(uploader=uploader).upload(UPLOAD)

    assert uploader.threads != [threading.get_ident()]


# --- reading the answer -------------------------------------------------------


async def test_the_receipt_reports_the_name_and_location_cloudinary_gave() -> None:
    stored = await _store(uploader=FakeCloudinary()).upload(UPLOAD)

    assert stored.success is True
    assert stored.key == "alpha-front"
    assert stored.url == "https://res.zoid.example/alpha.jpg"


async def test_an_insecure_url_is_still_a_location() -> None:
    response = {"public_id": "alpha-front", "url": "http://res.zoid.example/alpha.jpg"}

    stored = await _store(uploader=FakeCloudinary(response=response)).upload(UPLOAD)

    assert stored.url == "http://res.zoid.example/alpha.jpg"


async def test_a_response_that_is_an_object_is_read_the_same_way() -> None:
    response = SimpleNamespace(public_id="alpha-front", secure_url="https://cdn/alpha.jpg")

    stored = await _store(uploader=FakeCloudinary(response=response)).upload(UPLOAD)

    assert (stored.key, stored.url) == ("alpha-front", "https://cdn/alpha.jpg")


async def test_a_reply_with_nothing_in_it_reports_a_store_with_nothing_to_say() -> None:
    """A 200 we cannot read is not a crash, and not a location we invented."""
    stored = await _store(uploader=FakeCloudinary(response={})).upload(UPLOAD)

    assert stored.success is True
    assert stored.key is None
    assert stored.url is None


@pytest.mark.parametrize(
    "error",
    [
        param(GeneralError("Socket Error: connection reset"), id="unreachable"),
        param(AuthorizationRequired("Unknown credentials"), id="wrong-key"),
        param(BadRequest("Invalid image file"), id="rejected-by-provider"),
        param(NotFound("Server returned unexpected status code - 404"), id="no-such-folder"),
        param(RateLimited("Too many requests"), id="over-quota"),
        param(CloudinaryError("Unexpected error"), id="base-class"),
    ],
)
async def test_every_way_cloudinary_can_say_no_is_one_thing_to_the_caller(
    error: BaseException,
) -> None:
    """The SDK's hierarchy stops at the adapter; the contract sees a refusal."""
    stored = await _store(uploader=FakeCloudinary(error=error)).upload(UPLOAD)

    assert stored.success is False
    assert stored.key is None
    assert stored.url is None
    assert stored.message == str(error)


# --- what is refused before a provider is ever asked --------------------------


async def test_an_unstorable_file_never_reaches_the_provider() -> None:
    uploader = FakeCloudinary()

    with pytest.raises(ValidationError):
        await _store(uploader=uploader).upload(FileUpload(filename="../escape", content=b"x"))

    assert uploader.calls == []


async def test_an_unconfigured_account_is_reported_as_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deployment with no Cloudinary credentials says so, instead of failing
    somewhere inside the SDK with a message about signatures."""
    called = False

    def never(*args: Any, **kwargs: Any) -> Any:
        nonlocal called
        called = True
        return None

    monkeypatch.setattr(cloudinary.uploader, "upload", never)
    store = _store(cloud_name="", api_key="", api_secret="")

    with pytest.raises(ProviderNotConfiguredError) as refusal:
        await store.upload(UPLOAD)

    assert called is False
    assert "CLOUDINARY_CLOUD_NAME" in str(refusal.value)


@pytest.mark.parametrize(
    "missing",
    [
        param({"cloud_name": ""}, id="no-cloud"),
        param({"cloud_name": "   "}, id="blank-cloud"),
        param({"api_key": ""}, id="no-api-key"),
        param({"api_secret": ""}, id="no-api-secret"),
    ],
)
async def test_a_half_configured_account_is_refused_too(missing: dict[str, str]) -> None:
    with pytest.raises(ProviderNotConfiguredError):
        await _store(**{**ACCOUNT, **missing}).upload(UPLOAD)


# --- the SDK's own quirk ------------------------------------------------------


async def test_the_configured_account_is_the_one_the_sdk_signs_with(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real SDK, because its account is one process-global object.

    The adapter has to leave that configuration holding its own account at the
    moment a request is signed, and has to leave nothing of itself behind when it
    is done -- so this reads the SDK's live configuration from inside the call and
    puts back whatever it found.
    """
    config = cloudinary.config()
    original = dict(config.__dict__)
    signed_with: list[tuple[Any, Any]] = []

    def capture(file: Any, **options: Any) -> dict[str, Any]:
        signed_with.append((config.cloud_name, config.api_key))
        return RECEIPT

    monkeypatch.setattr(cloudinary.uploader, "upload", capture)
    try:
        stored = await _store(cloud_name="zoid-live").upload(UPLOAD)
    finally:
        config.__dict__.clear()
        config.__dict__.update(original)

    assert stored.success is True
    assert signed_with == [("zoid-live", ACCOUNT["api_key"])]
    # The account the test found is the account it leaves, whoever set it up.
    assert config.__dict__ == original
