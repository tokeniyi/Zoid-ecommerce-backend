"""Credential ORM model — a stored password for a user (auth-owned)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.persistence.sqlalchemy.models.user import UserRow
from app.infrastructure.persistence.sqlalchemy.session import Base


class CredentialRow(Base):
    __tablename__ = "credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    # Kept for login-by-email lookups; kept in sync with the user's email.
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[UserRow] = relationship(back_populates="credential")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<CredentialRow user_id={self.user_id} email={self.email!r}>"
