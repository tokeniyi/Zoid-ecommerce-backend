"""Community archive stories: a customer's memory, held until the shop approves it.

Plain, framework-free rules. A story is written by a signed-in customer and starts
*pending*: nothing a stranger typed appears on the storefront until the shop has
read it. The shop either approves it (it goes public) or rejects it (it stays
private to its author).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from app.shared.exceptions import ValidationError

TITLE_MAX = 150
AUTHOR_MAX = 80
LOCATION_MAX = 120
CATEGORY_MAX = 60
CONTENT_MIN = 10
CONTENT_MAX = 5000
IMAGE_URL_MAX = 500
DEFAULT_CATEGORY = "COMMUNITY STORY"

#: Fields an author may change on their own story.
EDITABLE_FIELDS = ("title", "author", "location", "year", "category", "content", "image_url")


class StoryStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


def tidy(text: str | None) -> str:
    """Trim, and collapse runs of spaces/tabs inside lines (paragraph breaks stay)."""
    lines = ((text or "").replace("\r\n", "\n").replace("\r", "\n")).split("\n")
    return "\n".join(" ".join(line.split()) for line in lines).strip()


@dataclass
class Story:
    id: int
    user_id: int | None
    title: str
    author: str
    content: str
    location: str = ""
    year: str = ""
    category: str = DEFAULT_CATEGORY
    image_url: str = ""
    status: StoryStatus = StoryStatus.PENDING
    #: The shop's note on a decision (why a story was rejected); private to the shop.
    moderation_note: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    reviewed_at: datetime | None = None

    @property
    def is_public(self) -> bool:
        return self.status is StoryStatus.APPROVED

    def edit(self, changes: dict[str, str]) -> None:
        """Apply an author's edit; the result must still be a valid story.

        Any edit sends the story back to *pending*: what the shop approved is
        what was approved, not whatever the author swaps in afterwards. A rejected
        story can be corrected and resubmitted the same way. A refused edit
        leaves the story exactly as it was.
        """
        unknown = set(changes) - set(EDITABLE_FIELDS)
        if unknown:
            raise ValidationError(f"Not editable on a story: {sorted(unknown)}.")
        before = {name: getattr(self, name) for name in changes}
        try:
            for name, value in changes.items():
                setattr(self, name, tidy(value) if name != "image_url" else value.strip())
            self.validate()
        except ValidationError:
            for name, value in before.items():
                setattr(self, name, value)
            raise
        if changes:
            self.status = StoryStatus.PENDING
            self.moderation_note = ""
            self.reviewed_at = None
            self.updated_at = datetime.now(UTC)

    def moderate(self, decision: StoryStatus, note: str = "") -> None:
        """Record the shop's decision: approve (publish) or reject."""
        if decision is StoryStatus.PENDING:
            raise ValidationError("A story is moderated to approved or rejected.")
        self.status = decision
        self.moderation_note = tidy(note)
        self.reviewed_at = datetime.now(UTC)

    def validate(self) -> None:
        if not self.title:
            raise ValidationError("A story needs a title.")
        if len(self.title) > TITLE_MAX:
            raise ValidationError(f"The title can be at most {TITLE_MAX} characters.")
        if not self.author:
            raise ValidationError("A story needs the author's name.")
        if len(self.author) > AUTHOR_MAX:
            raise ValidationError(f"The author's name can be at most {AUTHOR_MAX} characters.")
        if len(self.location) > LOCATION_MAX:
            raise ValidationError(f"The location can be at most {LOCATION_MAX} characters.")
        if len(self.category) > CATEGORY_MAX:
            raise ValidationError(f"The category can be at most {CATEGORY_MAX} characters.")
        if self.year and not (self.year.isdigit() and len(self.year) == 4):
            raise ValidationError("The year must be four digits, e.g. 1998.")
        if len(self.content) < CONTENT_MIN:
            raise ValidationError(f"A story needs at least {CONTENT_MIN} characters.")
        if len(self.content) > CONTENT_MAX:
            raise ValidationError(f"A story can be at most {CONTENT_MAX} characters.")
        if self.image_url:
            if len(self.image_url) > IMAGE_URL_MAX:
                raise ValidationError("The image address is too long.")
            # An address, never something a browser would run: no javascript:/data:
            # URLs, and no "//host" (a path that quietly means another site).
            url = self.image_url
            is_path = url.startswith("/") and not url.startswith("//")
            if not (is_path or url.startswith(("http://", "https://"))):
                raise ValidationError("The image must be an http(s) address or a site path.")
