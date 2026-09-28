"""Persistence contracts for the authentication domain.

`AbstractUserRepository` is re-exported from the users domain (one shared user
aggregate). `AbstractCredentialsRepository` is authentication-specific.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domains.auth.domain.entities import Credentials
from app.domains.users.domain.repositories import (  # re-export: shared contract
    AbstractUserRepository,
)

__all__ = ["AbstractUserRepository", "AbstractCredentialsRepository"]


class AbstractCredentialsRepository(ABC):
    """Read/write password `Credentials` records."""

    @abstractmethod
    async def add(self, credentials: Credentials) -> Credentials:
        """Persist credentials for a user."""

    @abstractmethod
    async def get_by_email(self, email: str) -> Credentials | None:
        """Return the credentials registered under ``email`` or ``None``."""

    @abstractmethod
    async def get_by_user_id(self, user_id: int) -> Credentials | None:
        """Return the credentials belonging to ``user_id`` or ``None``."""
