"""SQLAlchemy refund repository — implements the payments-domain contract."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.payments.domain.entities import Refund
from app.domains.payments.domain.enums import RefundStatus
from app.domains.payments.domain.repositories import AbstractRefundRepository
from app.infrastructure.persistence.sqlalchemy.models.refund import RefundRow


class SqlRefundRepository(AbstractRefundRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, refund: Refund) -> Refund:
        row = RefundRow(
            transaction_id=refund.transaction_id,
            reference=refund.reference,
            amount=refund.amount,
            currency=refund.currency,
            provider=refund.provider,
            status=refund.status.value,
            provider_refund_reference=refund.provider_refund_reference,
            reason=refund.reason,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return self._to_domain(row)

    async def get_by_reference(self, reference: str) -> Refund | None:
        row = (
            await self._session.execute(
                select(RefundRow).where(RefundRow.reference == reference)
            )
        ).scalar_one_or_none()
        return self._to_domain(row) if row is not None else None

    async def list_by_transaction_id(self, transaction_id: int) -> list[Refund]:
        rows = (
            await self._session.execute(
                select(RefundRow)
                .where(RefundRow.transaction_id == transaction_id)
                .order_by(RefundRow.id)
            )
        ).scalars().all()
        return [self._to_domain(row) for row in rows]

    async def total_refunded(self, transaction_id: int) -> Decimal:
        """Settled refunds only: a failed attempt returned nothing to anyone."""
        total = (
            await self._session.execute(
                select(func.coalesce(func.sum(RefundRow.amount), 0)).where(
                    RefundRow.transaction_id == transaction_id,
                    RefundRow.status == RefundStatus.SUCCEEDED.value,
                )
            )
        ).scalar_one()
        return Decimal(str(total))

    @staticmethod
    def _to_domain(row: RefundRow) -> Refund:
        return Refund(
            id=row.id,
            reference=row.reference,
            transaction_id=row.transaction_id,
            amount=row.amount,
            currency=row.currency,
            provider=row.provider,
            status=RefundStatus(row.status),
            provider_refund_reference=row.provider_refund_reference,
            reason=row.reason,
            created_at=row.created_at,
        )
