"""SQLAlchemy category repository — implements the products-domain contract."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.products.domain.entities import Category
from app.domains.products.domain.repositories import AbstractCategoryRepository
from app.infrastructure.persistence.sqlalchemy.models.category import CategoryRow


class SqlCategoryRepository(AbstractCategoryRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, category: Category) -> Category:
        row = CategoryRow(name=category.name, slug=category.slug)
        self._session.add(row)
        await self._session.flush()
        return Category(id=row.id, name=row.name, slug=row.slug)

    async def list(self) -> list[Category]:
        rows = (
            await self._session.execute(select(CategoryRow).order_by(CategoryRow.name))
        ).scalars().all()
        return [Category(id=row.id, name=row.name, slug=row.slug) for row in rows]
