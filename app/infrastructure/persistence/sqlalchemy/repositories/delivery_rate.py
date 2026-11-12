"""SQLAlchemy delivery-rate repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.delivery.domain.entities import DeliveryOption, DeliveryRate
from app.domains.delivery.domain.repositories import AbstractDeliveryRateRepository
from app.infrastructure.persistence.sqlalchemy.models.delivery_rate import DeliveryRateRow


class SqlDeliveryRateRepository(AbstractDeliveryRateRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_active(self) -> list[DeliveryRate]:
        rows = (
            await self._session.execute(
                select(DeliveryRateRow)
                .where(DeliveryRateRow.is_active.is_(True))
                .order_by(DeliveryRateRow.id)
            )
        ).scalars().all()
        return [self._to_domain(row) for row in rows]

    async def find_by_key(self, key: str) -> DeliveryRate | None:
        row = (
            await self._session.execute(select(DeliveryRateRow).where(DeliveryRateRow.key == key))
        ).scalar_one_or_none()
        return self._to_domain(row) if row is not None else None

    async def add(self, rate: DeliveryRate) -> DeliveryRate:
        row = DeliveryRateRow(
            key=rate.key,
            option=rate.option.value,
            state=rate.state,
            city=rate.city,
            university=rate.university,
            terminal=rate.terminal,
            fee=rate.fee,
            is_active=rate.is_active,
        )
        self._session.add(row)
        await self._session.flush()
        return self._to_domain(row)

    @staticmethod
    def _to_domain(row: DeliveryRateRow) -> DeliveryRate:
        return DeliveryRate(
            id=row.id,
            option=DeliveryOption(row.option),
            fee=row.fee,
            state=row.state,
            city=row.city,
            university=row.university,
            terminal=row.terminal,
            is_active=row.is_active,
        )
