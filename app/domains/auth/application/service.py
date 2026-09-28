"""Authentication use-case orchestration.

`AuthService` coordinates the repositories, the password-hashing contract and
the session strategy. It depends only on abstractions — no HTTP, no ORM, no
concrete crypto library — which is what the architecture requires so the
capability stays independently testable and replaceable.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domains.auth.domain.entities import Credentials, User
from app.domains.auth.domain.repositories import (
    AbstractCredentialsRepository,
    AbstractUserRepository,
)
from app.security.authentication.session import AbstractSessionStrategy
from app.security.password.hasher import PasswordHasher
from app.shared.exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)

MIN_PASSWORD_LENGTH = 8


def normalize_email(email: str) -> str:
    """Canonical form used for storage and lookup."""
    return email.strip().lower()


@dataclass(frozen=True)
class SignUpCommand:
    """Inputs for registering a new user."""

    name: str
    email: str
    password: str
    phone: str | None = None


@dataclass(frozen=True)
class AuthenticatedSession:
    """A user plus the freshly issued session token."""

    user: User
    token: str


class AuthService:
    def __init__(
        self,
        users: AbstractUserRepository,
        credentials: AbstractCredentialsRepository,
        hasher: PasswordHasher,
        session: AbstractSessionStrategy,
    ) -> None:
        self._users = users
        self._credentials = credentials
        self._hasher = hasher
        self._session = session

    async def sign_up(self, command: SignUpCommand) -> User:
        """Register a new user and store their credential."""
        email = normalize_email(command.email)
        if len(command.password) < MIN_PASSWORD_LENGTH:
            raise ValidationError(
                f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
            )
        if await self._users.get_by_email(email) is not None:
            raise ConflictError("A user with this email already exists.")

        user = await self._users.add(
            User(id=0, email=email, name=command.name.strip(), phone=command.phone)
        )
        await self._credentials.add(
            Credentials(
                email=email,
                password_hash=self._hasher.hash(command.password),
                user_id=user.id,
            )
        )
        return user

    async def log_in(self, email: str, password: str) -> AuthenticatedSession:
        """Verify credentials and, on success, open a session."""
        credentials = await self._credentials.get_by_email(normalize_email(email))
        if credentials is None or not self._hasher.verify(
            password, credentials.password_hash
        ):
            raise AuthenticationError("Invalid email or password.")

        user: User | None = None
        if credentials.user_id is not None:
            user = await self._users.get_by_id(credentials.user_id)
        if user is None:
            user = await self._users.get_by_email(normalize_email(email))
        if user is None:
            raise AuthenticationError("Invalid email or password.")

        token, _claims = self._session.issue(str(user.id), role=user.role)
        return AuthenticatedSession(user=user, token=token)

    async def get_user(self, user_id: int) -> User:
        """Return the user behind an authenticated session."""
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found.")
        return user
