"""Shared checkout/delivery fixtures for tests.

Delivery is priced from rate rows the shop owns, so any test that checks an order
out needs some. :data:`BASIC_RATES` is the smallest useful set and
:data:`CHECKOUT_DELIVERY` a form that it prices at :data:`STANDARD_FEE`.
"""

from __future__ import annotations

from decimal import Decimal

from app.domains.delivery.domain.entities import DeliveryDetails, DeliveryOption, DeliveryRate
from app.domains.delivery.domain.repositories import AbstractDeliveryRateRepository

STANDARD_FEE = Decimal("2500.00")
EXPRESS_FEE = Decimal("4500.00")

#: What a customer in Lagos fills in for ordinary home delivery.
CHECKOUT_DELIVERY: dict[str, str] = {
    "option": "standard",
    "state": "Lagos State",
    "city": "Yaba",
    "address": "12 Concrete Road, Yaba",
}

#: Lagos and Ogun home delivery, Lagos express, and free terminal pickup anywhere.
BASIC_RATES: tuple[DeliveryRate, ...] = (
    DeliveryRate(id=0, option=DeliveryOption.STANDARD, state="Lagos State", fee=STANDARD_FEE),
    DeliveryRate(id=0, option=DeliveryOption.STANDARD, state="Ogun State", fee=STANDARD_FEE),
    DeliveryRate(id=0, option=DeliveryOption.EXPRESS, state="Lagos State", fee=EXPRESS_FEE),
    DeliveryRate(id=0, option=DeliveryOption.PICKUP, fee=Decimal("0")),
)


def checkout_details(**overrides: str) -> DeliveryDetails:
    """The standard Lagos form as a domain object, with fields overridden."""
    return DeliveryDetails(**{**CHECKOUT_DELIVERY, **overrides})  # type: ignore[arg-type]


class InMemoryDeliveryRates(AbstractDeliveryRateRepository):
    """A rate table held in a list, for service-level tests."""

    def __init__(self, rates: tuple[DeliveryRate, ...] = BASIC_RATES) -> None:
        self._rates: list[DeliveryRate] = []
        for rate in rates:
            self._rates.append(
                DeliveryRate(
                    id=len(self._rates) + 1,
                    option=rate.option,
                    fee=rate.fee,
                    state=rate.state,
                    city=rate.city,
                    university=rate.university,
                    terminal=rate.terminal,
                    is_active=rate.is_active,
                )
            )

    async def list_active(self) -> list[DeliveryRate]:
        return [rate for rate in self._rates if rate.is_active]

    async def find_by_key(self, key: str) -> DeliveryRate | None:
        return next((rate for rate in self._rates if rate.key == key), None)

    async def add(self, rate: DeliveryRate) -> DeliveryRate:
        stored = DeliveryRate(
            id=len(self._rates) + 1, option=rate.option, fee=rate.fee, state=rate.state,
            city=rate.city, university=rate.university, terminal=rate.terminal,
            is_active=rate.is_active,
        )
        self._rates.append(stored)
        return stored
