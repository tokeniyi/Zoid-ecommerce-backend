"""The password hasher hashes/verifies behind its abstraction; the concrete
Argon2 algorithm never leaks to callers.
"""

from __future__ import annotations

from app.security.password import Argon2PasswordHasher, get_password_hasher
from app.security.password.hasher import PasswordHasher


def test_hash_and_verify_roundtrip() -> None:
    hasher = Argon2PasswordHasher()
    digest = hasher.hash("correct horse battery")
    assert digest.startswith("$argon2")
    assert digest != "correct horse battery"
    assert hasher.verify("correct horse battery", digest) is True
    assert hasher.verify("wrong password", digest) is False


def test_hashes_are_salted_and_unique() -> None:
    hasher = Argon2PasswordHasher()
    assert hasher.hash("same-secret") != hasher.hash("same-secret")


def test_verify_malformed_hash_returns_false() -> None:
    # A bad stored value must read as "no match", never raise.
    hasher = Argon2PasswordHasher()
    assert hasher.verify("anything", "not-a-real-hash") is False


def test_factory_returns_the_abstraction() -> None:
    assert isinstance(get_password_hasher(), PasswordHasher)
