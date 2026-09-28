"""SQLAlchemy cart repository — implements the cart-domain contract.

Items are eager-loaded so cart reads never trigger lazy IO. ``save`` reconciles
the persisted item rows with the in-memory aggregate (update existing lines,
insert new ones, delete removed ones) so callers mutate a plain ``Cart`` and
hand it back.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.cart.domain.entities import NEW_ITEM_ID, Cart, CartItem
from app.domains.cart.domain.repositories import AbstractCartRepository
from app.infrastructure.persistence.sqlalchemy.models.cart import CartRow
from app.infrastructure.persistence.sqlalchemy.models.cart_item import CartItemRow


class SqlCartRepository(AbstractCartRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, cart: Cart) -> Cart:
        row = CartRow(
            user_id=cart.user_id,
            guest_token=cart.guest_token,
            currency=cart.currency,
        )
        for item in cart.items:
            row.items.append(self._to_row(item))
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return self._to_domain(row)

    async def get_by_id(self, cart_id: int) -> Cart | None:
        row = await self._load(cart_id)
        return self._to_domain(row) if row is not None else None

    async def get_by_user_id(self, user_id: int) -> Cart | None:
        row = (
            await self._session.execute(select(CartRow).where(CartRow.user_id == user_id))
        ).scalar_one_or_none()
        if row is None:
            return None
        row = await self._load(row.id)
        return self._to_domain(row) if row is not None else None

    async def get_by_guest_token(self, guest_token: str) -> Cart | None:
        row = (
            await self._session.execute(
                select(CartRow).where(CartRow.guest_token == guest_token)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        row = await self._load(row.id)
        return self._to_domain(row) if row is not None else None

    async def save(self, cart: Cart) -> Cart:
        row = await self._load(cart.id)
        if row is None:  # pragma: no cover - defensive
            raise LookupError(f"Cart {cart.id} no longer exists")
        row.user_id = cart.user_id
        row.guest_token = cart.guest_token
        row.currency = cart.currency
        self._sync_items(row, cart)
        await self._session.flush()
        await self._session.refresh(row)
        reloaded = await self._load(row.id)
        assert reloaded is not None  # just flushed/loaded it
        return self._to_domain(reloaded)

    async def delete(self, cart: Cart) -> None:
        row = await self._session.get(CartRow, cart.id)
        if row is not None:
            await self._session.delete(row)
            await self._session.flush()

    async def _load(self, cart_id: int) -> CartRow | None:
        stmt = select(CartRow).options(selectinload(CartRow.items)).where(CartRow.id == cart_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    @staticmethod
    def _sync_items(row: CartRow, cart: Cart) -> None:
        existing_by_id = {item.id: item for item in row.items}
        keep_ids: set[int] = set()
        for item in cart.items:
            if item.id and item.id in existing_by_id:
                target = existing_by_id[item.id]
                target.quantity = item.quantity
                target.unit_price = item.unit_price
                keep_ids.add(item.id)
            else:
                new_row = SqlCartRepository._to_row(item)
                row.items.append(new_row)
                keep_ids.add(new_row.id)  # None until flush; harmless for the retain filter
        row.items[:] = [
            item for item in row.items if item.id is None or item.id in keep_ids
        ]

    @staticmethod
    def _to_row(item: CartItem) -> CartItemRow:
        kwargs = {}
        if item.id and item.id != NEW_ITEM_ID:
            kwargs["id"] = item.id
        return CartItemRow(
            **kwargs,
            variant_id=item.variant_id,
            product_slug=item.product_slug,
            product_name=item.product_name,
            size=item.size,
            quantity=item.quantity,
            unit_price=item.unit_price,
            image=item.image,
            currency=item.currency,
        )

    @staticmethod
    def _to_domain(row: CartRow) -> Cart:
        return Cart(
            id=row.id,
            guest_token=row.guest_token,
            user_id=row.user_id,
            currency=row.currency,
            items=[
                CartItem(
                    id=item.id,
                    variant_id=item.variant_id,
                    product_slug=item.product_slug,
                    product_name=item.product_name,
                    size=item.size,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    image=item.image,
                    currency=item.currency,
                )
                for item in row.items
            ],
        )
