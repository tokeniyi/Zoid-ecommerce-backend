"""SQLAlchemy wishlist repository — implements the wishlist-domain contract.

Items are eager-loaded so reads never trigger lazy IO. ``save`` reconciles the
persisted item rows with the in-memory aggregate (insert new, delete removed) so
callers mutate a plain ``Wishlist`` and hand it back.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.wishlist.domain.entities import NEW_ITEM_ID, Wishlist, WishlistItem
from app.domains.wishlist.domain.repositories import AbstractWishlistRepository
from app.infrastructure.persistence.sqlalchemy.models.wishlist import WishlistRow
from app.infrastructure.persistence.sqlalchemy.models.wishlist_item import (
    WishlistItemRow,
)


class SqlWishlistRepository(AbstractWishlistRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, wishlist: Wishlist) -> Wishlist:
        row = WishlistRow(user_id=wishlist.user_id)
        for item in wishlist.items:
            row.items.append(self._to_row(item))
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return self._to_domain(row)

    async def get_by_user_id(self, user_id: int) -> Wishlist | None:
        row = (
            await self._session.execute(
                select(WishlistRow)
                .options(selectinload(WishlistRow.items))
                .where(WishlistRow.user_id == user_id)
            )
        ).scalar_one_or_none()
        return self._to_domain(row) if row is not None else None

    async def save(self, wishlist: Wishlist) -> Wishlist:
        row = (
            await self._session.get(WishlistRow, wishlist.id)
            if wishlist.id
            else None
        )
        if row is None:  # pragma: no cover - defensive
            raise LookupError(f"Wishlist {wishlist.id} no longer exists")
        self._sync_items(row, wishlist)
        await self._session.flush()
        reloaded = (
            await self._session.execute(
                select(WishlistRow)
                .options(selectinload(WishlistRow.items))
                .where(WishlistRow.id == row.id)
            )
        ).scalar_one()
        return self._to_domain(reloaded)

    @staticmethod
    def _sync_items(row: WishlistRow, wishlist: Wishlist) -> None:
        existing_by_id = {item.id: item for item in row.items}
        keep_ids: set[int] = set()
        for item in wishlist.items:
            if item.id and item.id in existing_by_id:
                keep_ids.add(item.id)
            else:
                new_row = SqlWishlistRepository._to_row(item)
                row.items.append(new_row)
        row.items[:] = [
            item for item in row.items if item.id is None or item.id in keep_ids
        ]

    @staticmethod
    def _to_row(item: WishlistItem) -> WishlistItemRow:
        kwargs = {}
        if item.id and item.id != NEW_ITEM_ID:
            kwargs["id"] = item.id
        return WishlistItemRow(
            **kwargs,
            product_slug=item.product_slug,
            product_name=item.product_name,
            image=item.image,
            unit_price=item.unit_price,
            currency=item.currency,
        )

    @staticmethod
    def _to_domain(row: WishlistRow) -> Wishlist:
        return Wishlist(
            id=row.id,
            user_id=row.user_id,
            items=[
                WishlistItem(
                    id=item.id,
                    product_slug=item.product_slug,
                    product_name=item.product_name,
                    image=item.image,
                    unit_price=item.unit_price,
                    currency=item.currency,
                )
                for item in row.items
            ],
        )
