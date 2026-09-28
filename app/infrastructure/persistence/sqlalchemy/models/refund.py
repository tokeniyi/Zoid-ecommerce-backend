"""Refund ORM model -- one refund of all or part of a settled payment."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.sqlalchemy.session import Base


class RefundRow(Base):
    __tablename__ = "refunds"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Our reference for this refund, so a provider complaint can be traced back.
    reference: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="NGN", server_default=text("'NGN'")
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="unconfigured")
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="succeeded",
        server_default=text("'succeeded'"),
        index=True,
    )
    # Unique for the same reason the transaction's provider reference is: a
    # redelivered refund can never be booked as a second refund.
    provider_refund_reference: Mapped[str | None] = mapped_column(
        String(128), nullable=True, unique=True, index=True
    )
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<RefundRow id={self.id} reference={self.reference!r}>"
