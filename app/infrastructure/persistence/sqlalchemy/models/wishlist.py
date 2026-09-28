"""Wishlist ORM model — one saved-products list per user."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.persistence.sqlalchemy.session import Base

if TYPE_CHECKING:  # avoid import cycles; only needed for typing/relationships
    from app.infrastructure.persistence.sqlalchemy.models.wishlist_item import (
        WishlistItemRow,
    )


class WishlistRow(Base):
    __tablename__ = "wishlists"

    id: Mapped[int] = mapped_column(primary_key=True)
    # One wishlist per user; identity (not a path id) addresses it.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    items: Mapped[list[WishlistItemRow]] = relationship(
        back_populates="wishlist",
        cascade="all, delete-orphan",
        order_by="WishlistItemRow.id",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<WishlistRow id={self.id} user_id={self.user_id}>"
