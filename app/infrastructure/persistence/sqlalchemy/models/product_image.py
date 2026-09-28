"""Product image ORM model (gallery views)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.persistence.sqlalchemy.session import Base

if TYPE_CHECKING:
    from app.infrastructure.persistence.sqlalchemy.models.product import ProductRow


class ProductImageRow(Base):
    __tablename__ = "product_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    view: Mapped[str] = mapped_column(
        String(20), nullable=False, default="front", server_default=text("'front'")
    )
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    product: Mapped[ProductRow] = relationship(back_populates="images")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ProductImageRow id={self.id} view={self.view!r}>"
