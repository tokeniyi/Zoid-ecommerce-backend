"""SQLAlchemy credentials repository — implements the auth-domain contract."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.auth.domain.entities import Credentials
from app.domains.auth.domain.repositories import AbstractCredentialsRepository
from app.infrastructure.persistence.sqlalchemy.models.credential import CredentialRow


class SqlCredentialsRepository(AbstractCredentialsRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, credentials: Credentials) -> Credentials:
        row = CredentialRow(
            email=credentials.email,
            password_hash=credentials.password_hash,
            user_id=credentials.user_id,
        )
        self._session.add(row)
        await self._session.flush()
        return credentials

    async def get_by_email(self, email: str) -> Credentials | None:
        row = (
            await self._session.execute(
                select(CredentialRow).where(CredentialRow.email == email)
            )
        ).scalar_one_or_none()
        return self._to_domain(row) if row is not None else None

    async def get_by_user_id(self, user_id: int) -> Credentials | None:
        row = (
            await self._session.execute(
                select(CredentialRow).where(CredentialRow.user_id == user_id)
            )
        ).scalar_one_or_none()
        return self._to_domain(row) if row is not None else None

    @staticmethod
    def _to_domain(row: CredentialRow) -> Credentials:
        return Credentials(
            email=row.email,
            password_hash=row.password_hash,
            user_id=row.user_id,
        )
