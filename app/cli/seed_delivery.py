"""Load the shop's delivery rates — safe to run again.

    uv run python -m app.cli.seed_delivery

Delivery is priced from rate rows, and with no rows every place is "ask the shop".
This loads the storefront's current service area and prices (``data/delivery.json``):

* **standard** (hand delivery): every Lagos and Ogun address, Port Harcourt and its
  listed districts, and each listed university campus;
* **express**: Lagos, Ogun and Port Harcourt;
* **pickup**: free at any GUO terminal, with each verified terminal named so it is
  confirmed on sight; a terminal that is not listed is accepted but flagged for the
  shop to confirm.

A rate is identified by what it covers, so re-running adds only what is missing and
never changes a price the shop has already set.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.domains.delivery.domain.entities import DeliveryOption, DeliveryRate
from app.infrastructure.persistence.sqlalchemy.session import (
    build_sessionmaker,
    create_engine_from_url,
)
from app.infrastructure.persistence.sqlalchemy.unit_of_work import SqlAlchemyUnitOfWork

DATA_FILE = Path(__file__).parent / "data" / "delivery.json"
_RIVERS = "Rivers State"


@dataclass
class DeliverySeedReport:
    created: int = 0
    existing: int = 0

    def __str__(self) -> str:
        return f"created {self.created}, already present {self.existing}"


def load_data(path: Path = DATA_FILE) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_rates(data: dict[str, Any]) -> list[DeliveryRate]:
    """Every rate the reference data implies."""
    fees = {option: Decimal(fee) for option, fee in data["fees"].items()}
    rates: list[DeliveryRate] = []

    def add(option: DeliveryOption, **place: str | None) -> None:
        rates.append(DeliveryRate(id=0, option=option, fee=fees[option.value], **place))  # type: ignore[arg-type]

    for option in (DeliveryOption.STANDARD, DeliveryOption.EXPRESS):
        for state in data["hand_delivery_states"]:
            if state == _RIVERS:
                # Rivers is served in Port Harcourt only, not the whole state.
                for area in data["port_harcourt_areas"]:
                    add(option, state=state, city=area)
            else:
                add(option, state=state)
    for university in data["universities"]:
        add(DeliveryOption.STANDARD, state=university["state"], university=university["name"])

    add(DeliveryOption.PICKUP)  # anywhere: an unverified terminal is flagged, not refused
    for state, terminals in data["guo_terminals"].items():
        for terminal in terminals:
            add(DeliveryOption.PICKUP, state=state, terminal=terminal)
    return rates


async def seed(rates: list[DeliveryRate]) -> DeliverySeedReport:
    report = DeliverySeedReport()
    engine = create_engine_from_url()
    try:
        async with SqlAlchemyUnitOfWork(build_sessionmaker(engine)) as uow:
            for rate in rates:
                rate.validate()
                if await uow.delivery_rates.find_by_key(rate.key) is None:
                    await uow.delivery_rates.add(rate)
                    report.created += 1
                else:
                    report.existing += 1
            await uow.commit()
    finally:
        await engine.dispose()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--file", type=Path, default=DATA_FILE, help="delivery JSON to load")
    args = parser.parse_args(argv)
    print(f"Delivery rates: {asyncio.run(seed(build_rates(load_data(args.file))))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
