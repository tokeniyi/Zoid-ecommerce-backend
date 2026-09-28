"""Auth domain entities.

`Credentials` is an authentication-owned concept (a stored password). The
`User` aggregate itself is owned by the users domain and re-exported here so
auth code can reference the shared type from its own domain namespace.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domains.users.domain.entities import User  # re-export: shared aggregate

__all__ = ["User", "Credentials"]


@dataclass
class Credentials:
    """A stored password credential, keyed by email and linked to a user."""

    email: str
    password_hash: str
    user_id: int | None = None
