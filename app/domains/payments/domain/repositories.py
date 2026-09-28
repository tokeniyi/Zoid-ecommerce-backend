"""Contracts the payments domain requires from persistence."""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from app.domains.payments.domain.entities import Refund, Transaction, WebhookEvent


class AbstractTransactionRepository(ABC):
    """Persist and read payment transactions."""

    @abstractmethod
    async def add(self, transaction: Transaction) -> Transaction:
        """Store a new transaction and return it with its id assigned."""

    @abstractmethod
    async def get_by_id(self, transaction_id: int) -> Transaction | None:
        """Load a transaction by primary key."""

    @abstractmethod
    async def get_by_reference(self, reference: str) -> Transaction | None:
        """Load a transaction by the internal reference handed to the provider."""

    @abstractmethod
    async def get_latest_by_order_id(self, order_id: int) -> Transaction | None:
        """Most recent transaction for an order, or ``None`` if it was never paid."""

    @abstractmethod
    async def save(self, transaction: Transaction) -> Transaction:
        """Persist changes made to a loaded transaction."""


class AbstractRefundRepository(ABC):
    """The ledger of money going back to customers."""

    @abstractmethod
    async def add(self, refund: Refund) -> Refund:
        """Store a refund and return it with its id assigned."""

    @abstractmethod
    async def get_by_reference(self, reference: str) -> Refund | None:
        """Load a refund by its internal reference."""

    @abstractmethod
    async def list_by_transaction_id(self, transaction_id: int) -> list[Refund]:
        """Every refund recorded against a transaction, oldest first."""

    @abstractmethod
    async def total_refunded(self, transaction_id: int) -> Decimal:
        """Settled money already returned for a transaction (zero if none)."""


class AbstractWebhookEventRepository(ABC):
    """Receipts for provider notifications, the anchor of idempotency."""

    @abstractmethod
    async def add(self, event: WebhookEvent) -> WebhookEvent:
        """Record that a provider event arrived, and return it with its id."""

    @abstractmethod
    async def get_by_provider_and_event_id(
        self, provider: str, event_id: str
    ) -> WebhookEvent | None:
        """The stored receipt for this provider event, if we have one."""

    @abstractmethod
    async def save(self, event: WebhookEvent) -> WebhookEvent:
        """Persist changes made to a loaded event receipt."""
