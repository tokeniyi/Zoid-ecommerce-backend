"""Inventory ORM model — stock counts for a single variant."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.persistence.sqlalchemy.session import Base

if TYPE_CHECKING:
    from app.infrastructure.persistence.sqlalchemy.models.product_variant import (
        ProductVariantRow,
    )


class InventoryRow(Base):
    __tablename__ = "inventory"

    id: Mapped[int] = mapped_column(primary_key=True)
    variant_id: Mapped[int] = mapped_column(
        ForeignKey("product_variants.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    variant: Mapped[ProductVariantRow] = relationship(back_populates="inventory")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<InventoryRow variant_id={self.variant_id} quantity={self.quantity}>"
