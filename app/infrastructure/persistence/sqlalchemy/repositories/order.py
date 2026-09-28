"""SQLAlchemy order repository — implements the orders-domain contract.

Orders are written once at checkout and read back with their lines eager-loaded,
so no lazy IO happens on the async session. Money totals are denormalised onto
the order row from the domain's computed properties.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.orders.domain.entities import NEW_ITEM_ID, Order, OrderItem
from app.domains.orders.domain.enums import OrderStatus
from app.domains.orders.domain.repositories import AbstractOrderRepository
from app.infrastructure.persistence.sqlalchemy.models.order import OrderRow
from app.infrastructure.persistence.sqlalchemy.models.order_item import OrderItemRow


class SqlOrderRepository(AbstractOrderRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, order: Order) -> Order:
        row = OrderRow(
            user_id=order.user_id,
            reference=order.reference,
            status=order.status.value,
            currency=order.currency,
            subtotal=order.subtotal,
            total=order.total,
            item_count=order.item_count,
            contact_name=order.contact_name,
            contact_email=order.contact_email,
            contact_phone=order.contact_phone,
            address_line=order.address_line,
            city_state=order.city_state,
            notes=order.notes,
        )
        for item in order.items:
            row.items.append(self._to_row(item))
        self._session.add(row)
        await self._session.flush()
        return self._to_domain(await self._load(row.id))

    async def get_by_id(self, order_id: int) -> Order | None:
        row = await self._load(order_id)
        return self._to_domain(row) if row is not None else None

    async def list_by_user_id(self, user_id: int) -> list[Order]:
        rows = (
            await self._session.execute(
                select(OrderRow)
                .options(selectinload(OrderRow.items))
                .where(OrderRow.user_id == user_id)
                .order_by(OrderRow.id.desc())
            )
        ).scalars().all()
        return [self._to_domain(row) for row in rows]

    async def list_all(self, *, limit: int, offset: int) -> list[Order]:
        rows = (
            await self._session.execute(
                select(OrderRow)
                .options(selectinload(OrderRow.items))
                .order_by(OrderRow.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
        return [self._to_domain(row) for row in rows]

    async def count_all(self, *, status: OrderStatus | None = None) -> int:
        stmt = select(func.count()).select_from(OrderRow)
        if status is not None:
            stmt = stmt.where(OrderRow.status == status.value)
        return (await self._session.execute(stmt)).scalar_one()

    async def save(self, order: Order) -> Order:
        """Persist a status change on a loaded order.

        Ordered lines are an immutable checkout snapshot, so the only thing that
        ever differs between a loaded order and its row is the header state.
        """
        row = await self._load(order.id)
        if row is None:  # pragma: no cover - defensive
            raise LookupError(f"Order {order.id} no longer exists")
        row.status = order.status.value
        row.notes = order.notes
        await self._session.flush()
        return self._to_domain(await self._load(row.id))

    async def _load(self, order_id: int) -> OrderRow | None:
        return (
            await self._session.execute(
                select(OrderRow)
                .options(selectinload(OrderRow.items))
                .where(OrderRow.id == order_id)
            )
        ).scalar_one_or_none()

    @staticmethod
    def _to_row(item: OrderItem) -> OrderItemRow:
        kwargs = {}
        if item.id and item.id != NEW_ITEM_ID:
            kwargs["id"] = item.id
        return OrderItemRow(
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
    def _to_domain(row: OrderRow) -> Order:
        return Order(
            id=row.id,
            reference=row.reference,
            user_id=row.user_id,
            status=OrderStatus(row.status),
            currency=row.currency,
            contact_name=row.contact_name,
            contact_email=row.contact_email,
            contact_phone=row.contact_phone,
            address_line=row.address_line,
            city_state=row.city_state,
            notes=row.notes,
            created_at=row.created_at,
            items=[
                OrderItem(
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
