"""Roles and the authenticated principal.

A `Principal` is the minimal identity authorization needs: who the caller is
and which role they hold, derived from a verified session.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    """RBAC roles understood by the system."""

    CUSTOMER = "customer"
    ADMIN = "admin"


@dataclass(frozen=True)
class Principal:
    """An authorized caller: the user id plus its role."""

    user_id: int
    role: Role

    def has_role(self, role: Role) -> bool:
        return self.role is role

    def has_any_role(self, *roles: Role) -> bool:
        return self.role in roles


def parse_role(value: str) -> Role:
    """Coerce a raw role string into a `Role`.

    Unknown values default to the least-privileged role (customer).
    """
    try:
        return Role(value)
    except ValueError:
        return Role.CUSTOMER
