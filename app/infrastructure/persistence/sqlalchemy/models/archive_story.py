"""Archive story ORM model — a customer's memory awaiting or past moderation."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.sqlalchemy.session import Base


class ArchiveStoryRow(Base):
    __tablename__ = "archive_stories"

    id: Mapped[int] = mapped_column(primary_key=True)
    # A story outlives nothing it should not: it goes with its author's account.
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    author: Mapped[str] = mapped_column(String(80), nullable=False)
    location: Mapped[str] = mapped_column(
        String(120), nullable=False, default="", server_default=text("''")
    )
    year: Mapped[str] = mapped_column(
        String(4), nullable=False, default="", server_default=text("''")
    )
    category: Mapped[str] = mapped_column(
        String(60), nullable=False, default="COMMUNITY STORY",
        server_default=text("'COMMUNITY STORY'"), index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[str] = mapped_column(
        String(500), nullable=False, default="", server_default=text("''")
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default=text("'pending'"),
        index=True,
    )
    moderation_note: Mapped[str] = mapped_column(
        String(500), nullable=False, default="", server_default=text("''")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ArchiveStoryRow id={self.id} status={self.status!r}>"
