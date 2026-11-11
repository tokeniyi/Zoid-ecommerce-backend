"""Archive HTTP routes.

Reading is public (approved stories only). Writing needs a signed-in customer, who
can manage their own stories; the shop's moderation lives under ``/admin``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.domains.archives.api.schemas import (
    OwnStoryListResponse,
    OwnStoryResponse,
    StoryListResponse,
    StoryResponse,
    SubmitStoryRequest,
    UpdateStoryRequest,
    serialize_own,
    serialize_own_page,
    serialize_public_page,
    serialize_story,
)
from app.domains.archives.application.service import ArchiveService, NewStory
from app.infrastructure.container import get_archive_service
from app.security.authorization import Principal, require_authenticated_user
from app.shared.pagination import PaginationParams

router = APIRouter(prefix="/archives", tags=["archives"])


def get_pagination(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginationParams:
    return PaginationParams(page=page, page_size=page_size)


@router.get("", response_model=StoryListResponse)
async def list_stories(
    service: Annotated[ArchiveService, Depends(get_archive_service)],
    params: Annotated[PaginationParams, Depends(get_pagination)],
    category: Annotated[str | None, Query(max_length=60)] = None,
) -> StoryListResponse:
    """Approved stories, newest first."""
    return serialize_public_page(await service.list_public(params, category=category))


# Declared before "/{story_id}" so "mine" is never read as an id.
@router.get("/mine", response_model=OwnStoryListResponse)
async def list_my_stories(
    principal: Annotated[Principal, Depends(require_authenticated_user)],
    service: Annotated[ArchiveService, Depends(get_archive_service)],
    params: Annotated[PaginationParams, Depends(get_pagination)],
) -> OwnStoryListResponse:
    """The caller's own stories in every status, so they can see what is awaiting review."""
    return serialize_own_page(await service.list_mine(principal.user_id, params))


@router.get("/{story_id}", response_model=StoryResponse)
async def get_story(
    story_id: int,
    service: Annotated[ArchiveService, Depends(get_archive_service)],
) -> StoryResponse:
    """One approved story. Pending and rejected stories are not found."""
    return serialize_story(await service.get_public(story_id))


@router.post("", response_model=OwnStoryResponse, status_code=status.HTTP_201_CREATED)
async def submit_story(
    body: SubmitStoryRequest,
    principal: Annotated[Principal, Depends(require_authenticated_user)],
    service: Annotated[ArchiveService, Depends(get_archive_service)],
) -> OwnStoryResponse:
    """Submit a story. It stays pending, visible only to its author, until the shop approves it."""
    story = await service.submit(principal.user_id, NewStory(**body.model_dump()))
    return serialize_own(story)


@router.patch("/{story_id}", response_model=OwnStoryResponse)
async def update_story(
    story_id: int,
    body: UpdateStoryRequest,
    principal: Annotated[Principal, Depends(require_authenticated_user)],
    service: Annotated[ArchiveService, Depends(get_archive_service)],
) -> OwnStoryResponse:
    """Edit one of your own stories. Any edit sends it back to pending for the shop's review."""
    return serialize_own(await service.update_own(principal.user_id, story_id, body.changes()))


@router.delete("/{story_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_story(
    story_id: int,
    principal: Annotated[Principal, Depends(require_authenticated_user)],
    service: Annotated[ArchiveService, Depends(get_archive_service)],
) -> Response:
    """Delete one of your own stories (someone else's is not found)."""
    await service.delete_own(principal.user_id, story_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
