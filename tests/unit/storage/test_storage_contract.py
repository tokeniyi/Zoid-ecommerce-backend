"""The provider-independent file-storage contract, and the boundaries it draws.

Nothing here reaches a network or a provider: what is under test is the shape of
the seam itself -- what counts as a storable file, what a store promises, and
which imports the architecture forbids.

The structural tests at the bottom are the cheap, permanent version of the rule
"application code knows the storage contract, not Cloudinary/S3 implementation
details". Behavioural tests can only catch a violation in the path they
exercise; an import is visible all at once.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
from pytest import param

import app
from app.integrations.storage.contract import (
    AbstractFileStorage,
    FileUpload,
    StoredFile,
)
from app.shared.exceptions import ValidationError

_APP_ROOT = Path(app.__file__).parent
_STORAGE_PACKAGE = _APP_ROOT / "integrations" / "storage"

#: The one module business code is allowed to ask storage questions through.
#: The architecture's tree names no contract file for storage (unlike email's
#: ``sender.py``), so this package root -- which re-exports the adapters too --
#: is deliberately not on the list.
CONTRACT_MODULE = "app.integrations.storage.contract"

_UPLOAD = FileUpload(
    filename="alpha-front.jpg",
    content=b"\xff\xd8jpeg bytes\xff\xd9",
    content_type="image/jpeg",
)


# --- what counts as a storable file -------------------------------------------


@pytest.mark.parametrize(
    ("upload", "expected"),
    [
        param(_UPLOAD, "alpha-front.jpg", id="filename-only"),
        param(replace(_UPLOAD, key="jerseys/alpha"), "jerseys/alpha", id="asked-for-key"),
        param(replace(_UPLOAD, key="  jerseys/alpha  "), "jerseys/alpha", id="padded-key"),
        param(replace(_UPLOAD, key=""), "alpha-front.jpg", id="blank-key-falls-back"),
        param(replace(_UPLOAD, filename="  spaced.jpg  "), "spaced.jpg", id="padded-filename"),
    ],
)
def test_the_name_to_store_under(upload: FileUpload, expected: str) -> None:
    assert upload.object_name == expected


@pytest.mark.parametrize(
    "upload",
    [
        param(replace(_UPLOAD, content=b""), id="no-content"),
        param(replace(_UPLOAD, filename=""), id="no-filename"),
        param(replace(_UPLOAD, filename="   "), id="blank-filename"),
        param(replace(_UPLOAD, filename="/etc/passwd"), id="absolute-name"),
        param(replace(_UPLOAD, filename="../escape"), id="escapes-at-the-top"),
        param(replace(_UPLOAD, filename="images/../../escape"), id="escapes-from-a-folder"),
        param(replace(_UPLOAD, filename="a.jpg", key="../b.jpg"), id="key-escapes"),
    ],
)
def test_an_unstorable_file_is_refused(upload: FileUpload) -> None:
    with pytest.raises(ValidationError):
        upload.validate()


def test_a_sensible_file_in_a_folder_is_accepted() -> None:
    # A folder separator is how object stores draw namespaces; only a name that
    # walks *out* of the store is a problem.
    replace(_UPLOAD, filename="jerseys/club/alpha-front.jpg").validate()


def test_an_upload_cannot_be_rewritten_after_it_is_handed_over() -> None:
    """Providers are handed a file, so what they were handed must not move."""
    with pytest.raises(FrozenInstanceError):
        _UPLOAD.content_type = "image/png"  # type: ignore[misc]


# --- what a store reports back ------------------------------------------------


def test_a_stored_file_reports_where_it_landed() -> None:
    stored = StoredFile(success=True, key="alpha-front", url="https://cdn/alpha.jpg")

    assert stored.success is True
    assert stored.key == "alpha-front"
    assert stored.url == "https://cdn/alpha.jpg"
    assert stored.message is None


def test_a_provider_that_reports_no_location_is_still_a_success() -> None:
    """``url`` is what a provider *said*, not something the contract invents."""
    stored = StoredFile(success=True, key="jerseys/alpha.jpg")

    assert stored.url is None


def test_a_refusal_carries_the_reason_and_no_place() -> None:
    refused = StoredFile(success=False, message="the bucket does not exist")

    assert refused.success is False
    assert refused.key is None
    assert refused.url is None


# --- the storage interface ----------------------------------------------------


def test_the_contract_names_one_capability_and_no_provider() -> None:
    capabilities = {
        name for name in dir(AbstractFileStorage) if not name.startswith("_")
    }

    assert capabilities == {"provider", "upload"}
    assert AbstractFileStorage.provider == "none"


def test_a_store_that_cannot_store_is_not_a_store() -> None:
    class HalfBuilt(AbstractFileStorage):
        pass

    with pytest.raises(TypeError):
        HalfBuilt()  # type: ignore[abstract]


async def test_a_conforming_store_needs_only_to_answer_upload() -> None:
    class Minimal(AbstractFileStorage):
        async def upload(self, file: FileUpload) -> StoredFile:
            return StoredFile(success=True, key=file.object_name)

    stored = await Minimal().upload(_UPLOAD)

    assert stored.key == "alpha-front.jpg"


# --- the boundaries the architecture draws ------------------------------------


def _imported_modules(path: Path) -> set[str]:
    """Every module a file names in an import, in absolute form."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


def test_the_contract_itself_reaches_no_third_party_code() -> None:
    """A contract that imports an SDK has stopped being a seam."""
    imports = _imported_modules(_STORAGE_PACKAGE / "contract.py")
    roots = {name.split(".", 1)[0] for name in imports}
    # ``io`` is what a real file-shaped contract needs to describe; the point is
    # that no provider package appears.
    assert roots <= set(sys.stdlib_module_names) | {"app"}
    assert roots & {"cloudinary", "boto3", "botocore"} == set()


@pytest.mark.parametrize(
    ("sdk", "adapter"),
    [
        param("cloudinary", "cloudinary.py", id="cloudinary-sdk"),
        param("boto3", "s3.py", id="boto3"),
        param("botocore", "s3.py", id="botocore"),
    ],
)
def test_a_provider_sdk_is_reachable_only_from_its_own_adapter(
    sdk: str, adapter: str
) -> None:
    """The audit's "Application → Cloudinary SDK MUST NOT EXIST", for every module.

    Only the adapter that translates for that provider may name it -- including
    the factory, which builds adapters by class rather than by SDK.
    """
    allowed = _STORAGE_PACKAGE / adapter
    offenders = [
        path.relative_to(_APP_ROOT).as_posix()
        for path in _APP_ROOT.rglob("*.py")
        if path != allowed
        and any(name.split(".", 1)[0] == sdk for name in _imported_modules(path))
    ]

    assert offenders == []


def test_business_code_that_wants_storage_wants_the_contract() -> None:
    """Whatever the domains reach for when they need a file stored.

    Adapters, the factory and the package root are composition and provider
    detail; a domain importing one of those is a provider leaking into business
    logic. Today no domain stores files at all, and that is also fine -- the test
    is written as a rule rather than as a snapshot so it keeps holding once the
    admin surface starts uploading.
    """
    illegal = {
        name
        for path in (_APP_ROOT / "domains").rglob("*.py")
        for name in _imported_modules(path)
        if name.startswith("app.integrations.storage") and name != CONTRACT_MODULE
    }

    assert illegal == set()
