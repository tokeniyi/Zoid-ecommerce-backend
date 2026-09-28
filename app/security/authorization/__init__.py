"""Authorization capability: roles, permissions and reusable guards.

Kept separate from authentication (who you are) — this answers "are you allowed
to do this?". Routers compose these guards instead of re-implementing checks.
"""

from app.security.authorization.dependencies import (
    get_current_principal,
    require_admin,
    require_authenticated_user,
    require_permission,
    require_roles,
)
from app.security.authorization.permissions import (
    ROLE_PERMISSIONS,
    Permission,
    role_has_permission,
)
from app.security.authorization.roles import Principal, Role

__all__ = [
    "Principal",
    "Role",
    "Permission",
    "ROLE_PERMISSIONS",
    "role_has_permission",
    "get_current_principal",
    "require_authenticated_user",
    "require_admin",
    "require_roles",
    "require_permission",
]
