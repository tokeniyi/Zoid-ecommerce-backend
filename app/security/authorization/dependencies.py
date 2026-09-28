"""Reusable endpoint-protection dependencies.

These compose a verified session into an authorized `Principal`. Routers depend
on them (`Depends(require_admin)`, `Depends(require_permission(...))`) and never
implement authentication or role checks themselves.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends

from app.security.authentication import SessionClaims, get_current_session
from app.security.authorization.permissions import Permission, role_has_permission
from app.security.authorization.roles import Principal, Role, parse_role
from app.shared.exceptions import AuthorizationError


def _to_principal(claims: SessionClaims) -> Principal:
    return Principal(user_id=int(claims.subject), role=parse_role(claims.role))


def get_current_principal(
    claims: Annotated[SessionClaims, Depends(get_current_session)],
) -> Principal:
    """Resolve the authorized principal from a verified session.

    Raises `AuthenticationError` (401) upstream when no valid session exists.
    """
    return _to_principal(claims)


def require_authenticated_user(
    principal: Annotated[Principal, Depends(get_current_principal)],
) -> Principal:
    """Require any authenticated user."""
    return principal


def require_roles(*roles: Role) -> Callable[[Principal], Awaitable[Principal]]:
    """Require the caller to hold one of ``roles``."""

    async def dependency(
        principal: Annotated[Principal, Depends(get_current_principal)],
    ) -> Principal:
        if not principal.has_any_role(*roles):
            raise AuthorizationError("Insufficient role for this operation.")
        return principal

    return dependency


def require_admin(
    principal: Annotated[Principal, Depends(get_current_principal)],
) -> Principal:
    """Require the caller to be an administrator."""
    if principal.role is not Role.ADMIN:
        raise AuthorizationError("Admin privileges required.")
    return principal


def require_permission(
    permission: Permission,
) -> Callable[[Principal], Awaitable[Principal]]:
    """Require the caller's role to grant ``permission``."""

    async def dependency(
        principal: Annotated[Principal, Depends(get_current_principal)],
    ) -> Principal:
        if not role_has_permission(principal.role, permission):
            raise AuthorizationError(f"Missing permission: {permission.value}.")
        return principal

    return dependency
