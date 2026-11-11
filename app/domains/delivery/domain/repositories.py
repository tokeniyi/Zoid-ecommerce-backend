"""Persistence contract for delivery rates."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domains.delivery.domain.entities import DeliveryRate


class AbstractDeliveryRateRepository(ABC):
    """Read and add the shop's delivery pricing rules."""

    @abstractmethod
    async def list_active(self) -> list[DeliveryRate]:
        """Every rate currently in force."""

    @abstractmethod
    async def find_by_key(self, key: str) -> DeliveryRate | None:
        """The rate with this natural key (see ``DeliveryRate.key``), if any."""

    @abstractmethod
    async def add(self, rate: DeliveryRate) -> DeliveryRate:
        """Persist a new rate and return it with its id."""
