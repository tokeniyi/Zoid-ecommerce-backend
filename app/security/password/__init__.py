"""Password hashing capability. The concrete algorithm is hidden behind the
`PasswordHasher` contract so it can be swapped without touching callers.
"""

from app.security.password.factory import get_password_hasher
from app.security.password.hasher import Argon2PasswordHasher, PasswordHasher

__all__ = ["PasswordHasher", "Argon2PasswordHasher", "get_password_hasher"]
