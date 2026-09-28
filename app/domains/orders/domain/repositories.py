"""Contracts the orders domain requires from persistence."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domains.orders.domain.entities import Order
from app.domains.orders.domain.enums import OrderStatus


class AbstractOrderRepository(ABC):
    """Persist and read order aggregates."""

    @abstractmethod
    async def add(self, order: Order) -> Order:
        """Store a new order with its lines and return it with ids assigned."""

    @abstractmethod
    async def get_by_id(self, order_id: int) -> Order | None:
        """Load an order (with its lines) by primary key."""

    @abstractmethod
    async def list_by_user_id(self, user_id: int) -> list[Order]:
        """Return a user's orders, newest first."""

    @abstractmethod
    async def list_all(self, *, limit: int, offset: int) -> list[Order]:
        """Return a page of every customer's orders, newest first (the shop's ledger)."""

    @abstractmethod
    async def count_all(self, *, status: OrderStatus | None = None) -> int:
        """How many orders exist, optionally narrowed to one ``status``.

        Which statuses are worth counting is the caller's business; this only
        filters, so no lifecycle rule ends up written in SQL.
        """

    @abstractmethod
    async def save(self, order: Order) -> Order:
        """Persist changes made to a loaded order (status, notes)."""
