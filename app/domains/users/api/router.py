"""Users HTTP routes — self-service profile only.

The caller's identity comes from the verified session (`require_authenticated_user`),
never from the path, so every operation is implicitly scoped to the caller's own
record — one user cannot reach another's data through these endpoints.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.domains.users.api.schemas import (
    UserProfileResponse,
    UserProfileUpdateRequest,
)
from app.domains.users.application.service import (
    UpdateProfileCommand,
    UserService,
)
from app.domains.users.domain.entities import User
from app.infrastructure.container import get_user_service
from app.security.authorization import Principal, require_authenticated_user

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserProfileResponse)
async def get_own_profile(
    principal: Annotated[Principal, Depends(require_authenticated_user)],
    service: Annotated[UserService, Depends(get_user_service)],
) -> User:
    """Return the authenticated user's own profile."""
    return await service.get_profile(principal.user_id)


@router.put("/me", response_model=UserProfileResponse)
async def update_own_profile(
    body: UserProfileUpdateRequest,
    principal: Annotated[Principal, Depends(require_authenticated_user)],
    service: Annotated[UserService, Depends(get_user_service)],
) -> User:
    """Update the authenticated user's own profile."""
    return await service.update_profile(
        principal.user_id,
        UpdateProfileCommand(name=body.name, phone=body.phone),
    )
