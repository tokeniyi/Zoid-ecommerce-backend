"""Category ORM model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.persistence.sqlalchemy.session import Base

if TYPE_CHECKING:
    from app.infrastructure.persistence.sqlalchemy.models.product import ProductRow


class CategoryRow(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(140), unique=True, nullable=False, index=True)

    products: Mapped[list[ProductRow]] = relationship(back_populates="category")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<CategoryRow id={self.id} slug={self.slug!r}>"
