"""Wishlist HTTP endpoints (authenticated only).

The caller's identity comes from the verified session, never from the path, so
every operation is scoped to the caller's own wishlist.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.domains.wishlist.api.schemas import (
    AddWishlistItemRequest,
    WishlistResponse,
    serialize_wishlist,
)
from app.domains.wishlist.application.service import WishlistService
from app.infrastructure.container import get_wishlist_service
from app.security.authorization import Principal, require_authenticated_user

router = APIRouter(prefix="/wishlist", tags=["wishlist"])


@router.get("", response_model=WishlistResponse)
async def list_wishlist(
    principal: Annotated[Principal, Depends(require_authenticated_user)],
    service: Annotated[WishlistService, Depends(get_wishlist_service)],
) -> WishlistResponse:
    """Return the authenticated user's saved products."""
    wishlist = await service.list(principal.user_id)
    return serialize_wishlist(wishlist)


@router.post("/items", response_model=WishlistResponse)
async def add_item(
    body: AddWishlistItemRequest,
    principal: Annotated[Principal, Depends(require_authenticated_user)],
    service: Annotated[WishlistService, Depends(get_wishlist_service)],
) -> WishlistResponse:
    """Save a product to the wishlist (idempotent)."""
    wishlist = await service.add(principal.user_id, body.product_slug)
    return serialize_wishlist(wishlist)


@router.delete("/items/{product_slug}", response_model=WishlistResponse)
async def remove_item(
    product_slug: str,
    principal: Annotated[Principal, Depends(require_authenticated_user)],
    service: Annotated[WishlistService, Depends(get_wishlist_service)],
) -> WishlistResponse:
    """Remove a saved product from the wishlist."""
    wishlist = await service.remove(principal.user_id, product_slug)
    return serialize_wishlist(wishlist)
