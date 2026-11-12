"""Archive HTTP schemas.

Three views of one story, by who is looking: the **public** sees only what the shop
approved and nothing about who owns it; the **author** also sees where it stands;
the **shop** sees everything, including its own private moderation note.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.domains.archives.domain.entities import (
    AUTHOR_MAX,
    CATEGORY_MAX,
    CONTENT_MAX,
    IMAGE_URL_MAX,
    LOCATION_MAX,
    TITLE_MAX,
    Story,
    StoryStatus,
)
from app.shared.pagination import Page


class SubmitStoryRequest(BaseModel):
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    author: str = Field(min_length=1, max_length=AUTHOR_MAX)
    content: str = Field(min_length=1, max_length=CONTENT_MAX)
    location: str = Field(default="", max_length=LOCATION_MAX)
    year: str = Field(default="", max_length=4)
    category: str = Field(default="COMMUNITY STORY", max_length=CATEGORY_MAX)
    image_url: str = Field(default="", max_length=IMAGE_URL_MAX)


class UpdateStoryRequest(BaseModel):
    """Change what you named. Any edit sends the story back for the shop's review."""

    title: str | None = Field(default=None, min_length=1, max_length=TITLE_MAX)
    author: str | None = Field(default=None, min_length=1, max_length=AUTHOR_MAX)
    content: str | None = Field(default=None, min_length=1, max_length=CONTENT_MAX)
    location: str | None = Field(default=None, max_length=LOCATION_MAX)
    year: str | None = Field(default=None, max_length=4)
    category: str | None = Field(default=None, max_length=CATEGORY_MAX)
    image_url: str | None = Field(default=None, max_length=IMAGE_URL_MAX)

    def changes(self) -> dict[str, str]:
        return self.model_dump(exclude_unset=True, exclude_none=True)


class ModerationRequest(BaseModel):
    status: StoryStatus
    #: Kept private to the shop (why a story was rejected).
    note: str = Field(default="", max_length=500)


class StoryResponse(BaseModel):
    """A story as the public sees it: approved, and nothing about its owner."""

    id: int
    title: str
    author: str
    location: str
    year: str
    category: str
    content: str
    image_url: str
    created_at: datetime


class StoryListResponse(BaseModel):
    items: list[StoryResponse]
    page: int
    page_size: int
    total: int
    total_pages: int


class OwnStoryResponse(StoryResponse):
    """A story as its author sees it: also where it stands with the shop."""

    status: StoryStatus
    updated_at: datetime


class OwnStoryListResponse(BaseModel):
    items: list[OwnStoryResponse]
    page: int
    page_size: int
    total: int
    total_pages: int


class AdminStoryResponse(OwnStoryResponse):
    user_id: int | None
    moderation_note: str
    reviewed_at: datetime | None


class AdminStoryListResponse(BaseModel):
    items: list[AdminStoryResponse]
    page: int
    page_size: int
    total: int
    total_pages: int


def _public(story: Story) -> dict:
    return {
        "id": story.id, "title": story.title, "author": story.author,
        "location": story.location, "year": story.year, "category": story.category,
        "content": story.content, "image_url": story.image_url, "created_at": story.created_at,
    }


def serialize_story(story: Story) -> StoryResponse:
    return StoryResponse(**_public(story))


def serialize_own(story: Story) -> OwnStoryResponse:
    return OwnStoryResponse(**_public(story), status=story.status, updated_at=story.updated_at)


def serialize_admin(story: Story) -> AdminStoryResponse:
    return AdminStoryResponse(
        **_public(story), status=story.status, updated_at=story.updated_at,
        user_id=story.user_id, moderation_note=story.moderation_note,
        reviewed_at=story.reviewed_at,
    )


def _paged(page: Page, items: list) -> dict:
    return {
        "items": items, "page": page.page, "page_size": page.page_size,
        "total": page.total, "total_pages": page.total_pages,
    }


def serialize_public_page(page: Page[Story]) -> StoryListResponse:
    return StoryListResponse(**_paged(page, [serialize_story(s) for s in page.items]))


def serialize_own_page(page: Page[Story]) -> OwnStoryListResponse:
    return OwnStoryListResponse(**_paged(page, [serialize_own(s) for s in page.items]))


def serialize_admin_page(page: Page[Story]) -> AdminStoryListResponse:
    return AdminStoryListResponse(**_paged(page, [serialize_admin(s) for s in page.items]))
