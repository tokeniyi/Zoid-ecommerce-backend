"""Permissions and the role -> permission mapping.

Endpoints declare the permission they need; the guard resolves it against the
caller's role. Admin holds every permission; customers only self-service ones.
"""

from __future__ import annotations

from enum import StrEnum

from app.security.authorization.roles import Role


class Permission(StrEnum):
    """Discrete capabilities that can be granted to a role."""

    # Customer self-service.
    MANAGE_OWN_CART = "manage:own-cart"
    MANAGE_OWN_WISHLIST = "manage:own-wishlist"
    MANAGE_OWN_PROFILE = "manage:own-profile"
    MANAGE_OWN_ORDERS = "manage:own-orders"
    # Admin / management.
    VIEW_ADMIN_DASHBOARD = "view:admin-dashboard"
    MANAGE_PRODUCTS = "manage:products"
    MANAGE_INVENTORY = "manage:inventory"
    MANAGE_ORDERS = "manage:orders"
    MANAGE_USERS = "manage:users"


CUSTOMER_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.MANAGE_OWN_CART,
        Permission.MANAGE_OWN_WISHLIST,
        Permission.MANAGE_OWN_PROFILE,
        Permission.MANAGE_OWN_ORDERS,
    }
)

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.CUSTOMER: CUSTOMER_PERMISSIONS,
    # Admin is privileged with the full set rather than a hand-maintained list,
    # so new permissions are covered automatically.
    Role.ADMIN: frozenset(Permission),
}


def permissions_for_role(role: Role) -> frozenset[Permission]:
    """Return the permissions granted to ``role``."""
    return ROLE_PERMISSIONS.get(role, frozenset())


def role_has_permission(role: Role, permission: Permission) -> bool:
    """Whether ``role`` is granted ``permission``."""
    return permission in permissions_for_role(role)
