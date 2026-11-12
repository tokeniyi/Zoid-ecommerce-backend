"""SQLAlchemy archive-story repository."""

from __future__ import annotations

from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.archives.domain.entities import Story, StoryStatus
from app.domains.archives.domain.repositories import AbstractStoryRepository, StoryCriteria
from app.infrastructure.persistence.sqlalchemy.models.archive_story import ArchiveStoryRow


class SqlStoryRepository(AbstractStoryRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, story: Story) -> Story:
        row = ArchiveStoryRow(
            user_id=story.user_id, title=story.title, author=story.author,
            location=story.location, year=story.year, category=story.category,
            content=story.content, image_url=story.image_url, status=story.status.value,
            moderation_note=story.moderation_note,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return self._to_domain(row)

    async def get_by_id(self, story_id: int) -> Story | None:
        row = await self._session.get(ArchiveStoryRow, story_id)
        return self._to_domain(row) if row is not None else None

    async def save(self, story: Story) -> Story:
        row = await self._session.get(ArchiveStoryRow, story.id)
        if row is None:  # pragma: no cover - defensive
            raise LookupError(f"Story {story.id} no longer exists")
        row.title, row.author, row.location = story.title, story.author, story.location
        row.year, row.category, row.content = story.year, story.category, story.content
        row.image_url = story.image_url
        row.status = story.status.value
        row.moderation_note = story.moderation_note
        row.updated_at = story.updated_at
        row.reviewed_at = story.reviewed_at
        await self._session.flush()
        await self._session.refresh(row)
        return self._to_domain(row)

    async def delete(self, story_id: int) -> None:
        await self._session.execute(delete(ArchiveStoryRow).where(ArchiveStoryRow.id == story_id))

    async def search(self, criteria: StoryCriteria, *, limit: int, offset: int) -> list[Story]:
        rows = (
            await self._session.execute(
                select(ArchiveStoryRow)
                .where(*self._conditions(criteria))
                .order_by(ArchiveStoryRow.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
        return [self._to_domain(row) for row in rows]

    async def count(self, criteria: StoryCriteria) -> int:
        stmt = select(func.count()).select_from(ArchiveStoryRow).where(*self._conditions(criteria))
        return (await self._session.execute(stmt)).scalar_one()

    @staticmethod
    def _conditions(criteria: StoryCriteria) -> list[ColumnElement[bool]]:
        found: list[ColumnElement[bool]] = []
        if criteria.status is not None:
            found.append(ArchiveStoryRow.status == criteria.status.value)
        if criteria.user_id is not None:
            found.append(ArchiveStoryRow.user_id == criteria.user_id)
        if criteria.category:
            found.append(func.lower(ArchiveStoryRow.category) == criteria.category.strip().lower())
        return found

    @staticmethod
    def _to_domain(row: ArchiveStoryRow) -> Story:
        return Story(
            id=row.id, user_id=row.user_id, title=row.title, author=row.author,
            content=row.content, location=row.location, year=row.year,
            category=row.category, image_url=row.image_url, status=StoryStatus(row.status),
            moderation_note=row.moderation_note, created_at=row.created_at,
            updated_at=row.updated_at, reviewed_at=row.reviewed_at,
        )
