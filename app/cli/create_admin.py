"""Create the first administrator — or promote an existing customer.

    uv run python -m app.cli.create_admin --email owner@zoid.example --name "Zoid Owner"

Every ``/admin`` route needs a user whose role is ``admin``, and signup only ever
makes customers, so a fresh deployment has no way in. This command is that way in:
it is run by whoever operates the server, never exposed over HTTP.

* **New email:** creates the user with the ``admin`` role and a password.
* **Existing email:** promotes that user to ``admin``; their password is left
  alone. Running it again for an admin changes nothing.

The password is deliberately *not* a command-line argument (it would end up in
shell history and the process list). It is read from ``ZOID_ADMIN_PASSWORD`` when
set — handy for provisioning scripts — and otherwise asked for twice, hidden.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from enum import StrEnum

from pydantic import EmailStr, TypeAdapter
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domains.auth.application.service import MIN_PASSWORD_LENGTH, normalize_email
from app.domains.auth.domain.entities import Credentials, User
from app.infrastructure.persistence.sqlalchemy.models.role import RoleRow
from app.infrastructure.persistence.sqlalchemy.models.user import UserRow
from app.infrastructure.persistence.sqlalchemy.session import (
    build_sessionmaker,
    create_engine_from_url,
)
from app.infrastructure.persistence.sqlalchemy.unit_of_work import SqlAlchemyUnitOfWork
from app.security.password import get_password_hasher
from app.shared.exceptions import ValidationError

ADMIN_ROLE = "admin"
PASSWORD_ENV = "ZOID_ADMIN_PASSWORD"


_EMAIL = TypeAdapter(EmailStr)


def validated_email(email: str) -> str:
    """The email as the API will see it, or a ``ValidationError``.

    Uses the same validator as signup/login: an admin whose address the login
    endpoint would refuse could be created but never sign in.
    """
    try:
        return normalize_email(str(_EMAIL.validate_python(normalize_email(email))))
    except PydanticValidationError as exc:
        reason = exc.errors()[0]["msg"].removeprefix("value is not a valid email address: ")
        raise ValidationError(f"Not a usable email address: {reason}") from exc


class AdminOutcome(StrEnum):
    CREATED = "created"
    PROMOTED = "promoted"
    ALREADY_ADMIN = "already_admin"


async def ensure_admin(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    email: str,
    name: str,
    password: str | None,
    phone: str | None = None,
) -> AdminOutcome:
    """Make ``email`` an administrator, creating the account when it is new."""
    email = validated_email(email)
    async with SqlAlchemyUnitOfWork(sessionmaker) as uow:
        existing = await uow.users.get_by_email(email)

        if existing is None:
            if password is None or len(password) < MIN_PASSWORD_LENGTH:
                raise ValidationError(
                    f"A new admin needs a password of at least {MIN_PASSWORD_LENGTH} characters."
                )
            if not name.strip():
                raise ValidationError("A new admin needs a name.")
            user = await uow.users.add(
                User(id=0, email=email, name=name.strip(), phone=phone, role=ADMIN_ROLE)
            )
            await uow.credentials.add(
                Credentials(
                    email=email,
                    password_hash=get_password_hasher().hash(password),
                    user_id=user.id,
                )
            )
            await uow.commit()
            return AdminOutcome.CREATED

        if existing.role == ADMIN_ROLE:
            return AdminOutcome.ALREADY_ADMIN

        # The users contract has no "change role" use-case (nothing in the app
        # promotes anyone); this operator tool does it at the persistence edge.
        row = (
            await uow.session.execute(select(UserRow).where(UserRow.email == email))
        ).scalar_one()
        row.role = (
            await uow.session.execute(select(RoleRow).where(RoleRow.name == ADMIN_ROLE))
        ).scalar_one()
        await uow.commit()
        return AdminOutcome.PROMOTED


def _read_password(*, needed: bool) -> str | None:
    supplied = os.environ.get(PASSWORD_ENV)
    if supplied:
        return supplied
    if not needed or not sys.stdin.isatty():
        return None
    first = getpass.getpass("Password for the new admin: ")
    if first != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords do not match.")
    return first


async def _run(email: str, name: str, phone: str | None) -> AdminOutcome:
    engine = create_engine_from_url()
    try:
        sessionmaker = build_sessionmaker(engine)
        try:
            return await ensure_admin(
                sessionmaker, email=email, name=name, password=_read_password(needed=False),
                phone=phone,
            )
        except ValidationError:
            # A new account needs a password: ask for it now and try once more.
            return await ensure_admin(
                sessionmaker, email=email, name=name, password=_read_password(needed=True),
                phone=phone,
            )
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="", help="display name (required for a new account)")
    parser.add_argument("--phone", default=None)
    args = parser.parse_args(argv)

    try:
        outcome = asyncio.run(_run(args.email, args.name, args.phone))
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        {
            AdminOutcome.CREATED: f"Created admin {normalize_email(args.email)}.",
            AdminOutcome.PROMOTED: f"Promoted {normalize_email(args.email)} to admin.",
            AdminOutcome.ALREADY_ADMIN: f"{normalize_email(args.email)} is already an admin.",
        }[outcome]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
