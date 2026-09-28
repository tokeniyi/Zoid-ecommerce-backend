"""Selects the configured password implementation behind the abstraction.

This is the single point that decides *which* hasher the application uses, so
the choice can change without touching the authentication service.
"""

from __future__ import annotations

from functools import lru_cache

from app.security.password.hasher import Argon2PasswordHasher, PasswordHasher


@lru_cache
def get_password_hasher() -> PasswordHasher:
    """Return the process-wide password hasher (Argon2 by default)."""
    return Argon2PasswordHasher()
