"""SQLAlchemy webhook event repository — the idempotency ledger."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.payments.domain.entities import WebhookEvent
from app.domains.payments.domain.enums import WebhookKind
from app.domains.payments.domain.repositories import AbstractWebhookEventRepository
from app.infrastructure.persistence.sqlalchemy.models.webhook_event import (
    WebhookEventRow,
)


class SqlWebhookEventRepository(AbstractWebhookEventRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, event: WebhookEvent) -> WebhookEvent:
        row = WebhookEventRow(
            provider=event.provider,
            event_id=event.event_id,
            kind=event.kind.value,
            reference=event.reference,
            transaction_id=event.transaction_id,
            processed=event.processed,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return self._to_domain(row)

    async def get_by_provider_and_event_id(
        self, provider: str, event_id: str
    ) -> WebhookEvent | None:
        row = (
            await self._session.execute(
                select(WebhookEventRow).where(
                    WebhookEventRow.provider == provider,
                    WebhookEventRow.event_id == event_id,
                )
            )
        ).scalar_one_or_none()
        return self._to_domain(row) if row is not None else None

    async def save(self, event: WebhookEvent) -> WebhookEvent:
        row = (
            await self._session.get(WebhookEventRow, event.id) if event.id else None
        )
        if row is None:  # pragma: no cover - defensive
            raise LookupError(f"Webhook event {event.id} no longer exists")
        row.processed = event.processed
        row.transaction_id = event.transaction_id
        await self._session.flush()
        await self._session.refresh(row)
        return self._to_domain(row)

    @staticmethod
    def _to_domain(row: WebhookEventRow) -> WebhookEvent:
        return WebhookEvent(
            id=row.id,
            provider=row.provider,
            event_id=row.event_id,
            kind=WebhookKind(row.kind),
            reference=row.reference,
            transaction_id=row.transaction_id,
            processed=row.processed,
            received_at=row.received_at,
        )
