"""Authorization primitives: roles, permissions and principal helpers.

Pure unit tests over the RBAC logic (no HTTP), the heart of "are you allowed?".
"""

from __future__ import annotations

from app.security.authorization.permissions import (
    Permission,
    permissions_for_role,
    role_has_permission,
)
from app.security.authorization.roles import Principal, Role, parse_role


def test_admin_holds_every_permission() -> None:
    for permission in Permission:
        assert role_has_permission(Role.ADMIN, permission)


def test_customer_has_only_self_service_permissions() -> None:
    assert role_has_permission(Role.CUSTOMER, Permission.MANAGE_OWN_ORDERS)
    assert role_has_permission(Role.CUSTOMER, Permission.MANAGE_OWN_CART)
    assert not role_has_permission(Role.CUSTOMER, Permission.MANAGE_PRODUCTS)
    assert not role_has_permission(Role.CUSTOMER, Permission.MANAGE_USERS)
    assert not role_has_permission(Role.CUSTOMER, Permission.VIEW_ADMIN_DASHBOARD)


def test_permissions_for_unknown_role_is_empty() -> None:
    # Defensive: a role not in the map grants nothing.
    assert permissions_for_role(object()) == frozenset()  # type: ignore[arg-type]


def test_parse_role_coerces_and_defaults() -> None:
    assert parse_role("admin") is Role.ADMIN
    assert parse_role("customer") is Role.CUSTOMER
    assert parse_role("superuser") is Role.CUSTOMER  # unknown -> least privilege


def test_principal_role_helpers() -> None:
    admin = Principal(user_id=1, role=Role.ADMIN)
    customer = Principal(user_id=2, role=Role.CUSTOMER)
    assert admin.has_role(Role.ADMIN)
    assert admin.has_any_role(Role.CUSTOMER, Role.ADMIN)
    assert not customer.has_role(Role.ADMIN)
