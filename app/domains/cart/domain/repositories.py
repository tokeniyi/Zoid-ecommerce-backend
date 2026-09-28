"""Cart repository contract."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domains.cart.domain.entities import Cart


class AbstractCartRepository(ABC):
    """Persistence boundary for the cart aggregate."""

    @abstractmethod
    async def add(self, cart: Cart) -> Cart:
        """Persist a new cart and return it with its id assigned."""

    @abstractmethod
    async def get_by_id(self, cart_id: int) -> Cart | None:
        """Load a cart (with its items) by primary key."""

    @abstractmethod
    async def get_by_user_id(self, user_id: int) -> Cart | None:
        """Load the authenticated user's cart, if any."""

    @abstractmethod
    async def get_by_guest_token(self, guest_token: str) -> Cart | None:
        """Load a guest cart by its opaque token, if any."""

    @abstractmethod
    async def save(self, cart: Cart) -> Cart:
        """Persist changes to a cart and its items (add/update/remove)."""

    @abstractmethod
    async def delete(self, cart: Cart) -> None:
        """Remove a cart entirely (used when merging a guest cart away)."""
