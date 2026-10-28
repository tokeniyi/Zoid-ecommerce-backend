"""Reusable endpoint-protection dependencies.

These compose a verified session into an authorized `Principal`. Routers depend
on them (`Depends(require_admin)`, `Depends(require_permission(...))`) and never
implement authentication or role checks themselves.

Privileged guards (`require_admin`, `require_roles`, `require_permission`) read
the caller's role from the `AbstractRoleSource` on every request instead of
trusting the role claim in the token: a demoted admin is refused at once, and a
deleted user is no longer authenticated. `require_authenticated_user` needs only
a verified session.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends

from app.security.authentication import SessionClaims, get_current_session
from app.security.authorization.permissions import Permission, role_has_permission
from app.security.authorization.role_source import AbstractRoleSource, get_role_source
from app.security.authorization.roles import Principal, Role, parse_role
from app.shared.exceptions import AuthenticationError, AuthorizationError


def _to_principal(claims: SessionClaims) -> Principal:
    return Principal(user_id=int(claims.subject), role=parse_role(claims.role))


def get_current_principal(
    claims: Annotated[SessionClaims, Depends(get_current_session)],
) -> Principal:
    """Resolve the authorized principal from a verified session.

    Raises `AuthenticationError` (401) upstream when no valid session exists.
    The role here is the token's claim; privileged guards use
    `get_privileged_principal` instead.
    """
    return _to_principal(claims)


async def get_privileged_principal(
    principal: Annotated[Principal, Depends(get_current_principal)],
    roles: Annotated[AbstractRoleSource, Depends(get_role_source)],
) -> Principal:
    """The session's principal with the role the user holds now, from the database.

    Raises `AuthenticationError` (401) when the session's user no longer exists.
    """
    role = await roles.current_role(principal.user_id)
    if role is None:
        raise AuthenticationError("Not authenticated.")
    return Principal(user_id=principal.user_id, role=parse_role(role))


def require_authenticated_user(
    principal: Annotated[Principal, Depends(get_current_principal)],
) -> Principal:
    """Require any authenticated user."""
    return principal


def require_roles(*roles: Role) -> Callable[[Principal], Awaitable[Principal]]:
    """Require the caller to hold one of ``roles``."""

    async def dependency(
        principal: Annotated[Principal, Depends(get_privileged_principal)],
    ) -> Principal:
        if not principal.has_any_role(*roles):
            raise AuthorizationError("Insufficient role for this operation.")
        return principal

    return dependency


def require_admin(
    principal: Annotated[Principal, Depends(get_privileged_principal)],
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
        principal: Annotated[Principal, Depends(get_privileged_principal)],
    ) -> Principal:
        if not role_has_permission(principal.role, permission):
            raise AuthorizationError(f"Missing permission: {permission.value}.")
        return principal

    return dependency
