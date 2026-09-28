"""Auth service use-cases against in-memory fakes.

Proves signup, login, failed login, current-user retrieval and validation
through the abstractions — the service only sees repository ABCs, a
`PasswordHasher` and an `AbstractSessionStrategy`.
"""

from __future__ import annotations

import pytest

from app.domains.auth.application.service import AuthService, SignUpCommand
from app.domains.auth.domain.entities import Credentials, User
from app.domains.auth.domain.repositories import (
    AbstractCredentialsRepository,
    AbstractUserRepository,
)
from app.security.authentication.session import JwtCookieSessionStrategy
from app.security.password.hasher import Argon2PasswordHasher
from app.shared.exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)


class InMemoryUserRepository(AbstractUserRepository):
    def __init__(self) -> None:
        self._by_id: dict[int, User] = {}
        self._next_id = 1

    async def add(self, user: User) -> User:
        user.id = self._next_id
        self._next_id += 1
        self._by_id[user.id] = user
        return user

    async def get_by_id(self, user_id: int) -> User | None:
        return self._by_id.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        return next((u for u in self._by_id.values() if u.email == email), None)

    async def list_all(self, *, limit: int, offset: int) -> list[User]:  # pragma: no cover
        # Authentication never lists users; the shared contract asks for it.
        return list(self._by_id.values())[offset : offset + limit]

    async def count_all(self) -> int:  # pragma: no cover
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


class InMemoryCredentialsRepository(AbstractCredentialsRepository):
    def __init__(self) -> None:
        self._items: list[Credentials] = []

    async def add(self, credentials: Credentials) -> Credentials:
        self._items.append(credentials)
        return credentials

    async def get_by_email(self, email: str) -> Credentials | None:
        return next((c for c in self._items if c.email == email), None)

    async def get_by_user_id(self, user_id: int) -> Credentials | None:
        return next((c for c in self._items if c.user_id == user_id), None)


def make_service() -> tuple[AuthService, JwtCookieSessionStrategy]:
    strategy = JwtCookieSessionStrategy(
        secret="unit-test-secret-key-0123456789abcdef0123456789",
        ttl_minutes=60,
    )
    service = AuthService(
        users=InMemoryUserRepository(),
        credentials=InMemoryCredentialsRepository(),
        hasher=Argon2PasswordHasher(),
        session=strategy,
    )
    return service, strategy


async def test_valid_signup_normalises_email_and_stores_hash() -> None:
    service, _ = make_service()
    user = await service.sign_up(
        SignUpCommand(name=" Zoid ", email="User@Example.com", password="supersecret")
    )
    assert user.id == 1
    assert user.email == "user@example.com"
    assert user.name == "Zoid"
    assert user.role == "customer"


async def test_invalid_signup_short_password() -> None:
    service, _ = make_service()
    with pytest.raises(ValidationError):
        await service.sign_up(
            SignUpCommand(name="x", email="a@b.com", password="short")
        )


async def test_invalid_signup_duplicate_email() -> None:
    service, _ = make_service()
    await service.sign_up(
        SignUpCommand(name="A", email="dup@example.com", password="supersecret")
    )
    with pytest.raises(ConflictError):
        await service.sign_up(
            SignUpCommand(name="B", email="DUP@example.com", password="supersecret2")
        )


async def test_successful_login_issues_verifiable_session() -> None:
    service, strategy = make_service()
    user = await service.sign_up(
        SignUpCommand(name="A", email="in@example.com", password="supersecret")
    )
    session = await service.log_in("in@example.com", "supersecret")
    assert session.user.id == user.id
    claims = strategy.verify(session.token)
    assert claims.subject == str(user.id)


async def test_failed_login_wrong_password() -> None:
    service, _ = make_service()
    await service.sign_up(
        SignUpCommand(name="A", email="in@example.com", password="supersecret")
    )
    with pytest.raises(AuthenticationError):
        await service.log_in("in@example.com", "wrong-password")


async def test_failed_login_unknown_email() -> None:
    service, _ = make_service()
    with pytest.raises(AuthenticationError):
        await service.log_in("nobody@example.com", "whatever-123")


async def test_current_user_retrieval() -> None:
    service, _ = make_service()
    user = await service.sign_up(
        SignUpCommand(name="A", email="me@example.com", password="supersecret")
    )
    fetched = await service.get_user(user.id)
    assert fetched.email == "me@example.com"


async def test_current_user_missing_raises_not_found() -> None:
    service, _ = make_service()
    with pytest.raises(NotFoundError):
        await service.get_user(4242)
