"""The S3 adapter: what it hands the client, and what it makes of the answer.

The client is injected as a double, so these tests pin the *translation* --
contract file in, contract receipt out -- without a network or a bucket. The
credential tests are the exception: they go through boto3's own client factory,
because which arguments a bucket needs and when it needs them is boto3's business
rather than anything this adapter can be told to do.
"""

from __future__ import annotations

import threading
from typing import Any

import boto3
import pytest
from botocore.exceptions import (
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
)
from pytest import param

from app.integrations.storage.contract import FileUpload
from app.integrations.storage.s3 import S3FileStorage
from app.shared.exceptions import ProviderNotConfiguredError, ValidationError

BUCKET = "zoid-media"
REGION = "eu-west-2"
CREDENTIALS = {
    "access_key_id": "AKIAEXAMPLEKEY",
    "secret_access_key": "a-secret-that-is-not-the-real-one",
}
UPLOAD = FileUpload(
    filename="alpha-front.jpg",
    content=b"\xff\xd8jpeg bytes\xff\xd9",
    content_type="image/jpeg",
)


class FakeS3:
    """``client.put_object(**kwargs)``, with the answer scripted by the test."""

    def __init__(self, *, error: BaseException | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.threads: list[int] = []
        self.error = error

    def put_object(self, **kwargs: Any) -> dict[str, str]:
        self.calls.append(kwargs)
        self.threads.append(threading.get_ident())
        if self.error is not None:
            raise self.error
        return {"ETag": '"66f7a1"'}


def _store(
    *,
    bucket: str = BUCKET,
    region: str = REGION,
    access_key_id: str = CREDENTIALS["access_key_id"],
    secret_access_key: str = CREDENTIALS["secret_access_key"],
    endpoint_url: str = "",
    client: FakeS3 | None = None,
) -> S3FileStorage:
    return S3FileStorage(
        bucket=bucket,
        region=region,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        endpoint_url=endpoint_url,
        client=client,
    )


def _denied(code: str, message: str) -> ClientError:
    """A service-side refusal, in the shape botocore reports it."""
    return ClientError(
        error_response={"Error": {"Code": code, "Message": message}},
        operation_name="PutObject",
    )


# --- handing a file over ------------------------------------------------------


def test_the_adapter_labels_itself_for_the_provider_slot() -> None:
    assert S3FileStorage.provider == "s3"


async def test_a_file_is_handed_over_as_bucket_key_bytes_and_type() -> None:
    """Exact equality matters here: nothing provider-shaped goes missing, and
    nothing e-commerce-shaped sneaks in."""
    client = FakeS3()

    await _store(client=client).upload(UPLOAD)

    assert client.calls == [
        {
            "Bucket": BUCKET,
            "Key": "alpha-front.jpg",
            "Body": UPLOAD.content,
            "ContentType": "image/jpeg",
        }
    ]


async def test_a_declared_type_is_optional() -> None:
    """A caller that does not know the media type must not have one invented for it."""
    client = FakeS3()

    await _store(client=client).upload(FileUpload(filename="ledger.csv", content=b"a,b"))

    assert set(client.calls[0]) == {"Bucket", "Key", "Body"}


async def test_a_requested_name_is_where_the_file_lands() -> None:
    client = FakeS3()

    await _store(client=client).upload(
        FileUpload(filename="a.jpg", content=b"x", key="jerseys/club/alpha-front.jpg")
    )

    assert client.calls[0]["Key"] == "jerseys/club/alpha-front.jpg"


async def test_the_blocking_client_is_kept_off_the_event_loop() -> None:
    """boto3 is synchronous, so it must not run on the loop's thread."""
    client = FakeS3()

    await _store(client=client).upload(UPLOAD)

    assert client.threads != [threading.get_ident()]


# --- reading the answer -------------------------------------------------------


async def test_a_stored_object_reports_its_key_and_no_invented_location() -> None:
    """A successful ``put_object`` replies with an ETag and nothing else.

    Where the object is read back from -- a public bucket, a signed request, a CDN
    in front of either -- is a property of the deployment, so the adapter reports
    the one address the provider actually confirmed and leaves the rest alone.
    """
    stored = await _store(client=FakeS3()).upload(UPLOAD)

    assert stored.success is True
    assert stored.key == "alpha-front.jpg"
    assert stored.url is None


@pytest.mark.parametrize(
    "error",
    [
        param(_denied("AccessDenied", "not authorized to perform PutObject"), id="no-write-rights"),
        param(_denied("NoSuchBucket", "the specified bucket does not exist"), id="no-such-bucket"),
        param(EndpointConnectionError(endpoint_url="https://s3.example"), id="unreachable"),
        param(NoCredentialsError(), id="no-credentials-at-hand"),
    ],
)
async def test_every_way_the_provider_can_say_no_is_one_thing_to_the_caller(
    error: BaseException,
) -> None:
    """botocore's hierarchy stops at the adapter; the contract sees a refusal."""
    stored = await _store(client=FakeS3(error=error)).upload(UPLOAD)

    assert stored.success is False
    assert stored.key is None
    assert stored.url is None
    assert stored.message == str(error).strip()


# --- what is refused before a provider is ever asked --------------------------


async def test_an_unstorable_file_never_reaches_the_provider() -> None:
    client = FakeS3()

    with pytest.raises(ValidationError):
        await _store(client=client).upload(FileUpload(filename="a.jpg", content=b""))

    assert client.calls == []


@pytest.mark.parametrize(
    "overrides",
    [
        param({"bucket": ""}, id="no-bucket"),
        param({"region": ""}, id="no-region"),
        param({"bucket": "", "region": ""}, id="neither"),
        param({"bucket": "  ", "region": REGION}, id="blank-bucket"),
    ],
)
async def test_an_unaddressable_bucket_is_reported_as_unconfigured(
    overrides: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No bucket means no request to make, and boto3 must not be asked to guess."""
    built: list[str] = []

    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: built.append(str(args)))

    with pytest.raises(ProviderNotConfiguredError) as refusal:
        await _store(**{"bucket": BUCKET, "region": REGION, **overrides}).upload(UPLOAD)

    reason = str(refusal.value)
    assert "S3_BUCKET" in reason or "S3_REGION" in reason
    assert built == []


async def test_half_a_key_pair_is_reported_as_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One key without the other signs nothing, or signs wrongly."""
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: pytest.fail("no client"))

    with pytest.raises(ProviderNotConfiguredError) as refusal:
        await _store(secret_access_key="").upload(UPLOAD)

    assert "S3_ACCESS_KEY_ID" in str(refusal.value)


# --- the client this adapter builds for itself --------------------------------


async def test_the_configured_bucket_and_account_are_the_client_that_gets_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: dict[str, Any] = {}

    def capture(*args: Any, **kwargs: Any) -> FakeS3:
        built["args"] = args
        built.update(kwargs)
        return FakeS3()

    monkeypatch.setattr(boto3, "client", capture)
    store = _store(endpoint_url="https://spaces.example", client=None)

    stored = await store.upload(UPLOAD)

    assert stored.success is True
    assert built["args"] == ("s3",)
    assert built["region_name"] == REGION
    assert built["endpoint_url"] == "https://spaces.example"
    assert built["aws_access_key_id"] == CREDENTIALS["access_key_id"]
    assert built["aws_secret_access_key"] == CREDENTIALS["secret_access_key"]


async def test_a_bucket_reachable_without_environment_keys_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A role the process already holds is a normal way to reach a bucket."""
    built: dict[str, Any] = {}

    def capture(*args: Any, **kwargs: Any) -> FakeS3:
        built.update(kwargs)
        return FakeS3()

    monkeypatch.setattr(boto3, "client", capture)
    store = _store(access_key_id="", secret_access_key="", client=None)

    stored = await store.upload(UPLOAD)

    assert stored.success is True
    assert built["region_name"] == REGION
    assert "aws_access_key_id" not in built
    assert "endpoint_url" not in built


async def test_one_client_serves_every_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Building a client is per deployment, not per upload."""
    client = FakeS3()
    builds: list[str] = []
    monkeypatch.setattr(
        boto3, "client", lambda *args, **kwargs: builds.append(str(args)) or client
    )
    store = _store(client=None)

    await store.upload(UPLOAD)
    await store.upload(FileUpload(filename="alpha-back.jpg", content=b"y"))

    assert len(builds) == 1
    assert len(client.calls) == 2
