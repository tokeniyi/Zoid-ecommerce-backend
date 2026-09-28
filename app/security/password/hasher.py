"""Password-hashing abstraction.

Callers depend only on `PasswordHasher`. The concrete algorithm (Argon2 today)
is isolated here so it can be replaced (for example with bcrypt) without
touching the authentication service — see architecture section 6.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher


class PasswordHasher(ABC):
    """Framework-free contract for hashing and verifying passwords."""

    @abstractmethod
    def hash(self, password: str) -> str:
        """Return a hash digest for ``password``."""

    @abstractmethod
    def verify(self, password: str, hashed: str) -> bool:
        """Return ``True`` when ``password`` matches ``hashed``."""


class Argon2PasswordHasher(PasswordHasher):
    """`pwdlib`-backed Argon2id implementation.

    `pwdlib` internals stay confined to this class; nothing else in the codebase
    imports it.
    """

    def __init__(self) -> None:
        self._impl = PasswordHash((Argon2Hasher(),))

    def hash(self, password: str) -> str:
        return self._impl.hash(password)

    def verify(self, password: str, hashed: str) -> bool:
        try:
            return self._impl.verify(password, hashed)
        except Exception:  # malformed or unknown hash format -> treat as no match
            # A verification helper must never raise on attacker/DB-controlled
            # hash strings; a bad format simply means "does not match".
            return False
