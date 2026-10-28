"""Where privileged guards read a user's current role.

A session token carries the role it was issued with and stays valid for days, so
privileged guards do not trust that claim: they ask an `AbstractRoleSource` for
the role the user holds *now*. The concrete source lives at the composition root
(it reads the users table); security code only knows this contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class AbstractRoleSource(ABC):
    """Look up a user's current role."""

    @abstractmethod
    async def current_role(self, user_id: int) -> str | None:
        """Return ``user_id``'s role name, or ``None`` if the user does not exist."""


def get_role_source() -> AbstractRoleSource:
    """FastAPI dependency seat for the role source.

    The composition root binds this (``create_app`` overrides it). Left unbound
    it fails closed: a privileged route errors rather than fall back to the
    token's claim.
    """
    raise RuntimeError("No role source is wired; privileged routes cannot authorize.")
