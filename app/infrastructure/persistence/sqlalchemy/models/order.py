"""Order ORM model — a placed order aggregate root."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.persistence.sqlalchemy.session import Base

if TYPE_CHECKING:  # avoid import cycles; only needed for typing/relationships
    from app.infrastructure.persistence.sqlalchemy.models.order_item import (
        OrderItemRow,
    )


class OrderRow(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reference: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="PENDING_PAYMENT",
        server_default=text("'PENDING_PAYMENT'"),
        index=True,
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="NGN", server_default=text("'NGN'")
    )

    # Money is denormalised for cheap listing; lines keep their own unit prices.
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    contact_name: Mapped[str] = mapped_column(String(120), nullable=False)
    contact_email: Mapped[str] = mapped_column(String(320), nullable=False)
    contact_phone: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    address_line: Mapped[str] = mapped_column(String(300), nullable=False)
    city_state: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    items: Mapped[list[OrderItemRow]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="OrderItemRow.id",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<OrderRow id={self.id} reference={self.reference!r}>"
