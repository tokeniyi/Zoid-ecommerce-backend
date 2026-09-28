"""Transport-facing session token schema.

The decoded JSON Web Token claims, validated once at the boundary so the rest
of the strategy can trust their types.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TokenPayload(BaseModel):
    """Verified shape of an issued session token."""

    sub: str = Field(description="Subject — the authenticated user id.")
    iat: int = Field(description="Issued-at, seconds since the epoch.")
    exp: int = Field(description="Expiry, seconds since the epoch.")
    role: str = Field(default="customer", description="Authorization role claim.")
