"""Cart item ORM model — a snapshot line within a cart."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.persistence.sqlalchemy.session import Base

if TYPE_CHECKING:  # avoid import cycles; only needed for typing/relationships
    from app.infrastructure.persistence.sqlalchemy.models.cart import CartRow


class CartItemRow(Base):
    __tablename__ = "cart_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    cart_id: Mapped[int] = mapped_column(
        ForeignKey("carts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant_id: Mapped[int] = mapped_column(ForeignKey("product_variants.id"), nullable=False)

    # Display snapshot so the cart renders without loading the product aggregate.
    product_slug: Mapped[str] = mapped_column(String(160), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    size: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    image: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="NGN", server_default=text("'NGN'")
    )

    cart: Mapped[CartRow] = relationship(back_populates="items")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<CartItemRow id={self.id} variant_id={self.variant_id} qty={self.quantity}>"
