"""Archive story rules — pure, no database."""

from __future__ import annotations

import pytest

from app.domains.archives.application.service import ArchiveService, NewStory
from app.domains.archives.domain.entities import Story, StoryStatus, tidy
from app.domains.archives.domain.repositories import (
    AbstractStoryRepository,
    StoryCriteria,
)
from app.shared.exceptions import NotFoundError, ValidationError
from app.shared.pagination import PaginationParams

GOOD = "Watching Ronaldo on a CRT television in Surulere changed how I saw football."


def _story(**overrides: object) -> Story:
    fields: dict = {"id": 1, "user_id": 7, "title": "The 1998 Samba Memory",
                    "author": "Tunde O.", "content": GOOD, "year": "1998"}
    fields.update(overrides)
    return Story(**fields)


class MemoryStories(AbstractStoryRepository):
    def __init__(self) -> None:
        self.rows: dict[int, Story] = {}

    async def add(self, story: Story) -> Story:
        story.id = len(self.rows) + 1
        self.rows[story.id] = story
        return story

    async def get_by_id(self, story_id: int) -> Story | None:
        return self.rows.get(story_id)

    async def save(self, story: Story) -> Story:
        self.rows[story.id] = story
        return story

    async def delete(self, story_id: int) -> None:
        self.rows.pop(story_id, None)

    def _match(self, criteria: StoryCriteria) -> list[Story]:
        return sorted(
            (s for s in self.rows.values()
             if (criteria.status is None or s.status is criteria.status)
             and (criteria.user_id is None or s.user_id == criteria.user_id)
             and (not criteria.category or s.category.lower() == criteria.category.lower())),
            key=lambda s: s.id, reverse=True,
        )

    async def search(self, criteria: StoryCriteria, *, limit: int, offset: int) -> list[Story]:
        return self._match(criteria)[offset : offset + limit]

    async def count(self, criteria: StoryCriteria) -> int:
        return len(self._match(criteria))


# ── validation ──────────────────────────────────────────────────────────


def test_a_good_story_is_valid_and_starts_pending() -> None:
    story = _story()
    story.validate()
    assert story.status is StoryStatus.PENDING and story.is_public is False


@pytest.mark.parametrize(
    ("field", "value", "needle"),
    [
        ("title", "", "title"), ("title", "x" * 151, "title"),
        ("author", "", "author"), ("author", "x" * 81, "author"),
        ("content", "too short", "at least"), ("content", "x" * 5001, "at most"),
        ("year", "98", "four digits"), ("year", "nineteen", "four digits"),
        ("location", "x" * 121, "location"), ("category", "x" * 61, "category"),
        ("image_url", "javascript:alert(1)", r"http\(s\)"),
        ("image_url", "data:text/html;base64,PGgxPg==", r"http\(s\)"),
        ("image_url", "//evil.example/x.jpg", r"http\(s\)"),
        ("image_url", "ftp://host/x.jpg", r"http\(s\)"),
    ],
)
def test_invalid_stories_are_refused(field: str, value: str, needle: str) -> None:
    with pytest.raises(ValidationError, match=needle):
        _story(**{field: value}).validate()


@pytest.mark.parametrize("url", ["", "/manus-storage/story.jpg", "https://cdn.example.org/a.png",
                                 "http://example.org/a.png"])
def test_image_addresses_that_are_paths_or_http_are_fine(url: str) -> None:
    _story(image_url=url).validate()


def test_tidy_collapses_spaces_but_keeps_paragraphs() -> None:
    assert tidy("  Two   spaces \t here \r\n\r\n  next   para ") == "Two spaces here\n\nnext para"
    assert tidy(None) == ""


# ── editing and moderation ──────────────────────────────────────────────


def test_moderation_approves_or_rejects_and_notes_why() -> None:
    story = _story()
    story.moderate(StoryStatus.REJECTED, "  Not about football  ")
    assert (story.status, story.moderation_note) == (StoryStatus.REJECTED, "Not about football")
    assert story.reviewed_at is not None and story.is_public is False

    story.moderate(StoryStatus.APPROVED)
    assert story.is_public is True


def test_a_story_cannot_be_moderated_back_to_pending() -> None:
    with pytest.raises(ValidationError):
        _story().moderate(StoryStatus.PENDING)


def test_any_edit_sends_an_approved_story_back_for_review() -> None:
    story = _story()
    story.moderate(StoryStatus.APPROVED, "lovely")

    story.edit({"title": "  A   New   Title "})

    assert story.title == "A New Title"
    assert (story.status, story.moderation_note, story.reviewed_at) == (
        StoryStatus.PENDING, "", None,
    )
    assert story.is_public is False  # what was approved is no longer what is shown


def test_a_rejected_story_can_be_corrected_and_resubmitted() -> None:
    story = _story()
    story.moderate(StoryStatus.REJECTED, "too short")
    story.edit({"content": GOOD + " I was nine."})
    assert story.status is StoryStatus.PENDING


def test_a_refused_edit_changes_nothing_and_keeps_the_approval() -> None:
    story = _story()
    story.moderate(StoryStatus.APPROVED)

    with pytest.raises(ValidationError):
        story.edit({"title": "Fine", "year": "nope"})

    assert (story.title, story.year, story.status) == (
        "The 1998 Samba Memory", "1998", StoryStatus.APPROVED,
    )


def test_an_empty_edit_changes_nothing() -> None:
    story = _story()
    story.moderate(StoryStatus.APPROVED)
    story.edit({})
    assert story.status is StoryStatus.APPROVED


def test_only_the_authors_fields_can_be_edited() -> None:
    with pytest.raises(ValidationError, match="Not editable"):
        _story().edit({"status": "approved"})


# ── the service: who may see and change what ────────────────────────────


@pytest.fixture
def service() -> ArchiveService:
    return ArchiveService(MemoryStories())


async def test_submission_is_tidied_defaulted_and_pending(service: ArchiveService) -> None:
    story = await service.submit(
        7, NewStory(title="  A  Title ", author="Ada", content=GOOD, category="   ")
    )
    assert story.title == "A Title"
    assert story.category == "COMMUNITY STORY"
    assert story.year.isdigit() and len(story.year) == 4  # this year, by default
    assert story.status is StoryStatus.PENDING and story.user_id == 7


async def test_strangers_read_only_what_the_shop_approved(service: ArchiveService) -> None:
    pending = await service.submit(7, NewStory(title="Pending", author="A", content=GOOD))
    approved = await service.submit(7, NewStory(title="Approved", author="A", content=GOOD))
    await service.moderate(approved.id, StoryStatus.APPROVED)
    rejected = await service.submit(7, NewStory(title="Rejected", author="A", content=GOOD))
    await service.moderate(rejected.id, StoryStatus.REJECTED, "no")

    public = await service.list_public(PaginationParams())

    assert [s.title for s in public.items] == ["Approved"] and public.total == 1
    assert (await service.get_public(approved.id)).title == "Approved"
    for hidden in (pending, rejected):
        with pytest.raises(NotFoundError):
            await service.get_public(hidden.id)


async def test_an_author_sees_all_their_own_and_only_their_own(service: ArchiveService) -> None:
    mine = await service.submit(7, NewStory(title="Mine", author="A", content=GOOD))
    await service.submit(8, NewStory(title="Theirs", author="B", content=GOOD))

    listed = await service.list_mine(7, PaginationParams())

    assert [s.id for s in listed.items] == [mine.id] and listed.total == 1


async def test_someone_elses_story_is_not_found_to_edit_or_delete(
    service: ArchiveService,
) -> None:
    story = await service.submit(7, NewStory(title="Mine", author="A", content=GOOD))
    with pytest.raises(NotFoundError):
        await service.update_own(8, story.id, {"title": "Hijacked"})
    with pytest.raises(NotFoundError):
        await service.delete_own(8, story.id)
    with pytest.raises(NotFoundError):
        await service.update_own(7, 999, {"title": "x"})

    await service.delete_own(7, story.id)
    assert (await service.list_mine(7, PaginationParams())).total == 0


async def test_moderating_a_story_that_is_not_there(service: ArchiveService) -> None:
    with pytest.raises(NotFoundError):
        await service.moderate(404, StoryStatus.APPROVED)
