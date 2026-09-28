"""Order item ORM model — a snapshot line within an order."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.persistence.sqlalchemy.session import Base

if TYPE_CHECKING:  # avoid import cycles; only needed for typing/relationships
    from app.infrastructure.persistence.sqlalchemy.models.order import OrderRow


class OrderItemRow(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant_id: Mapped[int] = mapped_column(
        ForeignKey("product_variants.id"), nullable=False
    )

    # Snapshot of what was bought; the catalog may change, the order may not.
    product_slug: Mapped[str] = mapped_column(String(160), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    size: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    image: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="NGN", server_default=text("'NGN'")
    )

    order: Mapped[OrderRow] = relationship(back_populates="items")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<OrderItemRow id={self.id} slug={self.product_slug!r} qty={self.quantity}>"
