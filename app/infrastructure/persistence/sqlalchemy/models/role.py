"""Role ORM model (RBAC lookup table)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.persistence.sqlalchemy.session import Base

if TYPE_CHECKING:  # only for typing; avoids an import cycle with user.py
    from app.infrastructure.persistence.sqlalchemy.models.user import UserRow


class RoleRow(Base):
    """A named role; users reference it by id."""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)

    users: Mapped[list[UserRow]] = relationship(back_populates="role")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<RoleRow id={self.id} name={self.name!r}>"
