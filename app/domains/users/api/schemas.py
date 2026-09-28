"""Users API request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserProfileResponse(BaseModel):
    """Public shape of a user's own profile."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: EmailStr
    phone: str | None = None
    role: str
    created_at: datetime


class UserProfileUpdateRequest(BaseModel):
    """Self-service profile edit. Only mutable fields; omitted fields unchanged."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=32)
