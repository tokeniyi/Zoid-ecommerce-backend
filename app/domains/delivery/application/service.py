"""Delivery application service: quote what getting an order somewhere costs."""

from __future__ import annotations

from app.domains.delivery.domain.entities import DeliveryDetails, DeliveryQuote
from app.domains.delivery.domain.repositories import AbstractDeliveryRateRepository
from app.domains.delivery.domain.rules import quote as price_delivery


class DeliveryService:
    def __init__(self, rates: AbstractDeliveryRateRepository) -> None:
        self._rates = rates

    async def quote(self, details: DeliveryDetails) -> DeliveryQuote:
        """Check the form is complete for the chosen option, then price it.

        Used by the quote endpoint (so the shopper sees the fee before paying)
        and by checkout (so the fee charged is the one the server worked out).
        """
        details.validate()
        return price_delivery(details, await self._rates.list_active())
