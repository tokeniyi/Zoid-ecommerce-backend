"""Delivery rate ORM model — one pricing rule (see ``DeliveryRate``)."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Boolean, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.sqlalchemy.session import Base


class DeliveryRateRow(Base):
    __tablename__ = "delivery_rates"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: Natural identity of the rule; unique so seeding twice cannot duplicate it.
    key: Mapped[str] = mapped_column(String(600), unique=True, nullable=False)
    option: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # A NULL place field means "anywhere"; see DeliveryRate.specificity.
    state: Mapped[str | None] = mapped_column(String(80), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    university: Mapped[str | None] = mapped_column(String(200), nullable=True)
    terminal: Mapped[str | None] = mapped_column(String(200), nullable=True)
    fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<DeliveryRateRow {self.key!r} fee={self.fee}>"
