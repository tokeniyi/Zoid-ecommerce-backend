"""Product ORM model — the catalog aggregate root."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.persistence.sqlalchemy.session import Base

if TYPE_CHECKING:
    from app.infrastructure.persistence.sqlalchemy.models.category import CategoryRow
    from app.infrastructure.persistence.sqlalchemy.models.product_image import (
        ProductImageRow,
    )
    from app.infrastructure.persistence.sqlalchemy.models.product_variant import (
        ProductVariantRow,
    )


class ProductRow(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id"), nullable=False, index=True
    )
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="NGN", server_default=text("'NGN'")
    )

    tone: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    style: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    color: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    fit: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    fit_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    details: Mapped[str] = mapped_column(Text, nullable=False, default="")
    delivery: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    is_bestseller: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    is_special: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
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

    category: Mapped[CategoryRow] = relationship(back_populates="products", lazy="joined")
    images: Mapped[list[ProductImageRow]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductImageRow.position",
        lazy="selectin",
    )
    variants: Mapped[list[ProductVariantRow]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductVariantRow.id",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ProductRow id={self.id} slug={self.slug!r}>"
