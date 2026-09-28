"""UserService behaviour — proved against an in-memory repository.

No SQLAlchemy, no HTTP: this is the gate's "user business logic is isolated
from SQLAlchemy and HTTP".
"""

from __future__ import annotations

import pytest

from app.domains.users.application.service import (
    UpdateProfileCommand,
    UserService,
)
from app.domains.users.domain.entities import User
from app.domains.users.domain.repositories import AbstractUserRepository
from app.shared.exceptions import NotFoundError, ValidationError


class InMemoryUserRepository(AbstractUserRepository):
    def __init__(self) -> None:
        self._by_id: dict[int, User] = {}
        self._next = 1

    async def add(self, user: User) -> User:
        user.id = self._next
        self._by_id[user.id] = user
        self._next += 1
        return user

    async def get_by_id(self, user_id: int) -> User | None:
        return self._by_id.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        return next((u for u in self._by_id.values() if u.email == email), None)

    async def list_all(self, *, limit: int, offset: int) -> list[User]:
        return list(self._by_id.values())[offset : offset + limit]

    async def count_all(self) -> int:
        return len(self._by_id)

    async def update_profile(
        self,
        user_id: int,
        *,
        name: str | None = None,
        phone: str | None = None,
    ) -> User | None:
        user = self._by_id.get(user_id)
        if user is None:
            return None
        if name is not None:
            user.name = name
        if phone is not None:
            user.phone = phone
        return user


async def _seed(users: InMemoryUserRepository, email: str, name: str) -> User:
    return await users.add(User(id=0, email=email, name=name, phone=None))


@pytest.fixture
def repo() -> InMemoryUserRepository:
    return InMemoryUserRepository()


@pytest.fixture
def service(repo: InMemoryUserRepository) -> UserService:
    return UserService(repo)


async def test_get_profile_returns_own_user(
    service: UserService, repo: InMemoryUserRepository
) -> None:
    created = await _seed(repo, "alice@example.com", "Alice")

    fetched = await service.get_profile(created.id)

    assert fetched.id == created.id
    assert fetched.email == "alice@example.com"


async def test_get_profile_missing_user_raises(service: UserService) -> None:
    with pytest.raises(NotFoundError):
        await service.get_profile(999)


async def test_update_profile_applies_changes(
    service: UserService, repo: InMemoryUserRepository
) -> None:
    created = await _seed(repo, "bob@example.com", "Bob")

    updated = await service.update_profile(
        created.id,
        UpdateProfileCommand(name="  Robert  ", phone="+1000000000"),
    )

    assert updated.name == "Robert"  # trimmed
    assert updated.phone == "+1000000000"


async def test_update_profile_leaves_unset_fields_unchanged(
    service: UserService, repo: InMemoryUserRepository
) -> None:
    created = await _seed(repo, "carol@example.com", "Carol")
    await repo.update_profile(created.id, phone="+1555")

    updated = await service.update_profile(created.id, UpdateProfileCommand(name="Caroline"))

    assert updated.name == "Caroline"
    assert updated.phone == "+1555"  # untouched by this command


async def test_update_profile_blank_name_rejected(
    service: UserService, repo: InMemoryUserRepository
) -> None:
    created = await _seed(repo, "dave@example.com", "Dave")

    with pytest.raises(ValidationError):
        await service.update_profile(created.id, UpdateProfileCommand(name="   "))


async def test_update_profile_scoped_to_given_user_only(
    service: UserService, repo: InMemoryUserRepository
) -> None:
    a = await _seed(repo, "a@example.com", "A")
    b = await _seed(repo, "b@example.com", "B")

    await service.update_profile(a.id, UpdateProfileCommand(name="A-new"))

    assert (await repo.get_by_id(b.id)).name == "B"  # B unaffected
    assert (await repo.get_by_id(a.id)).name == "A-new"
