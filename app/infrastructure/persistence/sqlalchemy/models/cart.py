"""Cart ORM model — a guest or authenticated cart aggregate root."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.persistence.sqlalchemy.session import Base

if TYPE_CHECKING:  # avoid import cycles; only needed for typing/relationships
    from app.infrastructure.persistence.sqlalchemy.models.cart_item import CartItemRow


class CartRow(Base):
    __tablename__ = "carts"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Exactly one owner: a guest token (anonymous) or a user id (authenticated).
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    guest_token: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="NGN", server_default=text("'NGN'")
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

    items: Mapped[list[CartItemRow]] = relationship(
        back_populates="cart",
        cascade="all, delete-orphan",
        order_by="CartItemRow.id",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<CartRow id={self.id} user_id={self.user_id}>"
