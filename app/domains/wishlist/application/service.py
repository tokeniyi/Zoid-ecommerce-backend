"""Wishlist application service.

Every operation is keyed by the authenticated ``user_id`` (taken from the
session at the edge, never from the request body/path), so a shopper only ever
touches their own wishlist. Products are validated against the catalog and a few
display fields are snapshotted on save.
"""

from __future__ import annotations

from decimal import Decimal

from app.domains.products.domain.repositories import AbstractProductRepository
from app.domains.wishlist.domain.entities import Wishlist, WishlistItem
from app.domains.wishlist.domain.repositories import AbstractWishlistRepository
from app.shared.exceptions import NotFoundError


class WishlistService:
    def __init__(
        self,
        *,
        wishlists: AbstractWishlistRepository,
        products: AbstractProductRepository,
    ) -> None:
        self._wishlists = wishlists
        self._products = products

    async def list(self, user_id: int) -> Wishlist:
        """Return the user's wishlist without creating an empty one."""
        existing = await self._wishlists.get_by_user_id(user_id)
        if existing is not None:
            return existing
        return Wishlist(id=0, user_id=user_id, items=[])

    async def add(self, user_id: int, product_slug: str) -> Wishlist:
        """Save a product to the wishlist (idempotent on slug)."""
        product = await self._products.get_by_slug(product_slug)
        if product is None or not product.is_active:
            raise NotFoundError("Product not found")

        wishlist = await self._load_or_create(user_id)
        if wishlist.has(product.slug):
            return wishlist

        wishlist.add_item(
            WishlistItem(
                id=0,
                product_slug=product.slug,
                product_name=product.name,
                image=product.primary_image or "",
                unit_price=Decimal(product.price),
                currency=product.currency,
            )
        )
        return await self._wishlists.save(wishlist)

    async def remove(self, user_id: int, product_slug: str) -> Wishlist:
        """Remove a saved product; 404 when it was not on the wishlist."""
        wishlist = await self._wishlists.get_by_user_id(user_id)
        if wishlist is None or not wishlist.remove_item(product_slug):
            raise NotFoundError("Wishlist item not found")
        return await self._wishlists.save(wishlist)

    async def _load_or_create(self, user_id: int) -> Wishlist:
        existing = await self._wishlists.get_by_user_id(user_id)
        if existing is not None:
            return existing
        return await self._wishlists.add(Wishlist(id=0, user_id=user_id, items=[]))
