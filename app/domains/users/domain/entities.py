"""Users domain entities.

The `User` aggregate is owned here and shared by the authentication domain,
which verifies credentials that belong to a user. Plain, framework-free object.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class User:
    """An application user / authenticated principal."""

    id: int
    email: str
    name: str
    phone: str | None = None
    role: str = "customer"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
