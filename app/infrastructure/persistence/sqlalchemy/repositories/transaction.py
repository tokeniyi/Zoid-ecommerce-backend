"""SQLAlchemy transaction repository — implements the payments-domain contract."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.payments.domain.entities import Transaction
from app.domains.payments.domain.enums import PaymentStatus
from app.domains.payments.domain.repositories import AbstractTransactionRepository
from app.infrastructure.persistence.sqlalchemy.models.transaction import TransactionRow


class SqlTransactionRepository(AbstractTransactionRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, transaction: Transaction) -> Transaction:
        row = TransactionRow(
            order_id=transaction.order_id,
            reference=transaction.reference,
            provider=transaction.provider,
            status=transaction.status.value,
            amount=transaction.amount,
            currency=transaction.currency,
            provider_reference=transaction.provider_reference,
            checkout_url=transaction.checkout_url,
            failure_reason=transaction.failure_reason,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return self._to_domain(row)

    async def get_by_id(self, transaction_id: int) -> Transaction | None:
        row = await self._session.get(TransactionRow, transaction_id)
        return self._to_domain(row) if row is not None else None

    async def get_by_reference(self, reference: str) -> Transaction | None:
        row = (
            await self._session.execute(
                select(TransactionRow).where(TransactionRow.reference == reference)
            )
        ).scalar_one_or_none()
        return self._to_domain(row) if row is not None else None

    async def get_latest_by_order_id(self, order_id: int) -> Transaction | None:
        row = (
            await self._session.execute(
                select(TransactionRow)
                .where(TransactionRow.order_id == order_id)
                .order_by(TransactionRow.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return self._to_domain(row) if row is not None else None

    async def save(self, transaction: Transaction) -> Transaction:
        row = (
            await self._session.get(TransactionRow, transaction.id)
            if transaction.id
            else None
        )
        if row is None:  # pragma: no cover - defensive
            raise LookupError(f"Transaction {transaction.id} no longer exists")
        row.status = transaction.status.value
        row.provider = transaction.provider
        row.provider_reference = transaction.provider_reference
        row.checkout_url = transaction.checkout_url
        row.failure_reason = transaction.failure_reason
        await self._session.flush()
        await self._session.refresh(row)
        return self._to_domain(row)

    @staticmethod
    def _to_domain(row: TransactionRow) -> Transaction:
        return Transaction(
            id=row.id,
            reference=row.reference,
            order_id=row.order_id,
            amount=row.amount,
            currency=row.currency,
            provider=row.provider,
            status=PaymentStatus(row.status),
            provider_reference=row.provider_reference,
            checkout_url=row.checkout_url,
            failure_reason=row.failure_reason,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
