"""Persistence contract for archive stories."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.domains.archives.domain.entities import Story, StoryStatus


@dataclass(frozen=True)
class StoryCriteria:
    """Which stories to look at. Every field is optional."""

    status: StoryStatus | None = None
    user_id: int | None = None
    category: str | None = None


class AbstractStoryRepository(ABC):
    @abstractmethod
    async def add(self, story: Story) -> Story:
        """Persist a new story and return it with its id."""

    @abstractmethod
    async def get_by_id(self, story_id: int) -> Story | None:
        """The story with this id, in any status, or ``None``."""

    @abstractmethod
    async def save(self, story: Story) -> Story:
        """Persist an edit or a moderation decision."""

    @abstractmethod
    async def delete(self, story_id: int) -> None:
        """Remove a story."""

    @abstractmethod
    async def search(self, criteria: StoryCriteria, *, limit: int, offset: int) -> list[Story]:
        """Stories matching ``criteria``, newest first."""

    @abstractmethod
    async def count(self, criteria: StoryCriteria) -> int:
        """How many stories match ``criteria``."""
