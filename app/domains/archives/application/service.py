"""Archive stories: submit, read, manage your own, and (for the shop) moderate.

What may be seen by whom is decided here, not in the router: a stranger reads only
approved stories; an author also reads and manages their own, whatever their
status; the shop sees everything.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.domains.archives.domain.entities import DEFAULT_CATEGORY, Story, StoryStatus, tidy
from app.domains.archives.domain.repositories import AbstractStoryRepository, StoryCriteria
from app.shared.exceptions import NotFoundError
from app.shared.pagination import Page, PaginationParams


@dataclass(frozen=True)
class NewStory:
    title: str
    author: str
    content: str
    location: str = ""
    year: str = ""
    category: str = DEFAULT_CATEGORY
    image_url: str = ""


class ArchiveService:
    def __init__(self, stories: AbstractStoryRepository) -> None:
        self._stories = stories

    # ── customers ────────────────────────────────────────────────────

    async def submit(self, user_id: int, new: NewStory) -> Story:
        """Take a customer's story. It waits, unseen by anyone else, for the shop."""
        story = Story(
            id=0,
            user_id=user_id,
            title=tidy(new.title),
            author=tidy(new.author),
            content=tidy(new.content),
            location=tidy(new.location),
            year=new.year.strip() or str(datetime.now(UTC).year),
            category=tidy(new.category) or DEFAULT_CATEGORY,
            image_url=new.image_url.strip(),
        )
        story.validate()
        return await self._stories.add(story)

    async def list_public(
        self, params: PaginationParams, *, category: str | None = None
    ) -> Page[Story]:
        """Approved stories, newest first — what the storefront shows."""
        return await self._page(
            StoryCriteria(status=StoryStatus.APPROVED, category=category), params
        )

    async def get_public(self, story_id: int) -> Story:
        story = await self._stories.get_by_id(story_id)
        if story is None or not story.is_public:
            raise NotFoundError("Story not found.")
        return story

    async def list_mine(self, user_id: int, params: PaginationParams) -> Page[Story]:
        """The caller's own stories in every status, so they can see what is pending."""
        return await self._page(StoryCriteria(user_id=user_id), params)

    async def update_own(self, user_id: int, story_id: int, changes: dict[str, str]) -> Story:
        story = await self._own(user_id, story_id)
        story.edit(changes)
        return await self._stories.save(story)

    async def delete_own(self, user_id: int, story_id: int) -> None:
        story = await self._own(user_id, story_id)
        await self._stories.delete(story.id)

    # ── the shop ─────────────────────────────────────────────────────

    async def list_for_moderation(
        self, params: PaginationParams, *, status: StoryStatus | None = None
    ) -> Page[Story]:
        """Every story, oldest-pending first is the shop's to-do; here: newest first."""
        return await self._page(StoryCriteria(status=status), params)

    async def moderate(self, story_id: int, decision: StoryStatus, note: str = "") -> Story:
        story = await self._stories.get_by_id(story_id)
        if story is None:
            raise NotFoundError("Story not found.")
        story.moderate(decision, note)
        return await self._stories.save(story)

    # ── helpers ──────────────────────────────────────────────────────

    async def _own(self, user_id: int, story_id: int) -> Story:
        """Someone else's story is not found, exactly like one that does not exist."""
        story = await self._stories.get_by_id(story_id)
        if story is None or story.user_id != user_id:
            raise NotFoundError("Story not found.")
        return story

    async def _page(self, criteria: StoryCriteria, params: PaginationParams) -> Page[Story]:
        return Page(
            items=await self._stories.search(criteria, limit=params.limit, offset=params.offset),
            page=params.page,
            page_size=params.page_size,
            total=await self._stories.count(criteria),
        )
