"""Product variant ORM model (a purchasable size, with 1:1 inventory)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.persistence.sqlalchemy.session import Base

if TYPE_CHECKING:
    from app.infrastructure.persistence.sqlalchemy.models.inventory import InventoryRow
    from app.infrastructure.persistence.sqlalchemy.models.product import ProductRow


class ProductVariantRow(Base):
    __tablename__ = "product_variants"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sku: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    size: Mapped[str] = mapped_column(String(20), nullable=False)

    product: Mapped[ProductRow] = relationship(back_populates="variants")
    inventory: Mapped[InventoryRow] = relationship(
        back_populates="variant",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="joined",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ProductVariantRow sku={self.sku!r} size={self.size!r}>"
