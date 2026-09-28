"""Users application service — self-service profile operations.

Depends only on the `AbstractUserRepository` contract. Kept separate from the
authentication internals: this is about the profile, not about credentials or
sessions.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domains.users.domain.entities import User
from app.domains.users.domain.repositories import AbstractUserRepository
from app.shared.exceptions import NotFoundError, ValidationError


@dataclass(frozen=True)
class UpdateProfileCommand:
    """Mutable self-service profile fields. ``None`` means "leave unchanged"."""

    name: str | None = None
    phone: str | None = None


class UserService:
    def __init__(self, users: AbstractUserRepository) -> None:
        self._users = users

    async def get_profile(self, user_id: int) -> User:
        """Return the caller's own profile."""
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found.")
        return user

    async def update_profile(
        self,
        user_id: int,
        command: UpdateProfileCommand,
    ) -> User:
        """Update the caller's own profile.

        Only name/phone are self-service mutable; there is no target id in the
        request, so a caller can only ever affect their own record.
        """
        if command.name is not None and not command.name.strip():
            raise ValidationError("Name must not be blank.")
        user = await self._users.update_profile(
            user_id,
            name=command.name.strip() if command.name is not None else None,
            phone=command.phone,
        )
        if user is None:
            raise NotFoundError("User not found.")
        return user
