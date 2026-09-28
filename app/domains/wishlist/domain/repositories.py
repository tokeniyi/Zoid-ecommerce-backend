"""Wishlist repository contract."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domains.wishlist.domain.entities import Wishlist


class AbstractWishlistRepository(ABC):
    """Persistence boundary for the wishlist aggregate."""

    @abstractmethod
    async def add(self, wishlist: Wishlist) -> Wishlist:
        """Persist a new wishlist and return it with its id assigned."""

    @abstractmethod
    async def get_by_user_id(self, user_id: int) -> Wishlist | None:
        """Load the user's wishlist (with its items), if any."""

    @abstractmethod
    async def save(self, wishlist: Wishlist) -> Wishlist:
        """Persist changes to a wishlist and its items (add/remove)."""
