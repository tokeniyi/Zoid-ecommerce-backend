"""SQLAlchemy user repository — implements the users-domain contract.

Maps between the `UserRow` ORM model and the framework-free `User` aggregate.
The role is normalised through the `roles` lookup table.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.users.domain.entities import User
from app.domains.users.domain.repositories import AbstractUserRepository
from app.infrastructure.persistence.sqlalchemy.models.role import RoleRow
from app.infrastructure.persistence.sqlalchemy.models.user import UserRow

DEFAULT_ROLE = "customer"


class SqlUserRepository(AbstractUserRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: User) -> User:
        role = await self._get_or_create_role(user.role or DEFAULT_ROLE)
        row = UserRow(email=user.email, name=user.name, phone=user.phone, role=role)
        self._session.add(row)
        await self._session.flush()
        return self._to_domain(row)

    async def get_by_id(self, user_id: int) -> User | None:
        row = await self._session.get(UserRow, user_id)
        return self._to_domain(row) if row is not None else None

    async def get_by_email(self, email: str) -> User | None:
        row = (
            await self._session.execute(select(UserRow).where(UserRow.email == email))
        ).scalar_one_or_none()
        return self._to_domain(row) if row is not None else None

    async def list_all(self, *, limit: int, offset: int) -> list[User]:
        stmt = select(UserRow).order_by(UserRow.id).limit(limit).offset(offset)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [self._to_domain(row) for row in rows]

    async def count_all(self) -> int:
        stmt = select(func.count()).select_from(UserRow)
        return (await self._session.execute(stmt)).scalar_one()

    async def update_profile(
        self,
        user_id: int,
        *,
        name: str | None = None,
        phone: str | None = None,
    ) -> User | None:
        row = await self._session.get(UserRow, user_id)
        if row is None:
            return None
        if name is not None:
            row.name = name
        if phone is not None:
            row.phone = phone
        await self._session.flush()
        return self._to_domain(row)

    async def _get_or_create_role(self, name: str) -> RoleRow:
        role = (
            await self._session.execute(select(RoleRow).where(RoleRow.name == name))
        ).scalar_one_or_none()
        if role is None:
            role = RoleRow(name=name)
            self._session.add(role)
            await self._session.flush()
        return role

    @staticmethod
    def _to_domain(row: UserRow) -> User:
        return User(
            id=row.id,
            email=row.email,
            name=row.name,
            phone=row.phone,
            role=row.role.name,
            created_at=row.created_at,
        )
