"""Webhook event ORM model -- the receipt for one provider notification."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.sqlalchemy.session import Base


class WebhookEventRow(Base):
    __tablename__ = "webhook_events"
    # The idempotency key. Providers redeliver, and their event ids repeat; this
    # constraint is what makes "have we already acted on this?" a database
    # question rather than a hope.
    __table_args__ = (
        UniqueConstraint("provider", "event_id", name="uq_webhook_event_provider_event"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    #: What the event meant, in this application's vocabulary (``WebhookKind``).
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # The transaction this notification was about, when it named one.
    reference: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: False for an event recorded but deliberately not acted on.
    processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<WebhookEventRow id={self.id} event_id={self.event_id!r}>"
