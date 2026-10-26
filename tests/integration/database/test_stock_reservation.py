"""Stock reservation under concurrent checkouts, against real PostgreSQL.

Two customers checking out the last unit at the same moment must not both get
it. Each checkout runs in its own unit of work (its own connection and
transaction), exactly as two concurrent requests do. The interleaving is
forced: the second checkout reads stock while the first has reserved but not
yet committed, which is the window a read-check-write reservation loses.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine

from app.domains.products.domain.entities import (
    Category,
    Inventory,
    Product,
    ProductVariant,
)
from app.infrastructure.persistence.sqlalchemy.session import (
    build_sessionmaker,
    create_engine_from_url,
)
from app.infrastructure.persistence.sqlalchemy.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.database

# Long enough for the second transaction to reach the row before the first
# commits; short enough not to slow the suite. The assertions do not depend on
# the second transaction blocking, only on it having read before the commit.
HOLD_SECONDS = 0.5


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_engine_from_url()
    yield engine
    await engine.dispose()


async def _seed_variant(engine: AsyncEngine, *, stock: int) -> int:
    tag = uuid4().hex[:8]
    product = Product(
        id=0,
        slug=f"race-{tag}",
        name=f"Race {tag}",
        category=Category(id=0, name="Race", slug="race"),
        price=Decimal("1000.00"),
        variants=[
            ProductVariant(id=0, sku=f"race-{tag}-M", size="M", inventory=Inventory(quantity=stock))
        ],
    )
    async with SqlAlchemyUnitOfWork(build_sessionmaker(engine)) as uow:
        created = await uow.products.add(product)
        await uow.commit()
    return created.variants[0].id


async def _reserved(engine: AsyncEngine, variant_id: int) -> int:
    async with SqlAlchemyUnitOfWork(build_sessionmaker(engine)) as uow:
        product = next(
            p for p in await uow.products.list_active(limit=100, offset=0)
            if p.variants[0].id == variant_id
        )
        return product.variants[0].inventory.reserved


async def _race(engine: AsyncEngine, variant_id: int, quantity: int) -> tuple[bool, bool]:
    """Two checkouts for ``quantity``; the second starts inside the first's transaction."""
    first_reserved = asyncio.Event()
    sessions = build_sessionmaker(engine)

    async def first() -> bool:
        async with SqlAlchemyUnitOfWork(sessions) as uow:
            granted = await uow.products.reserve_stock(variant_id, quantity)
            first_reserved.set()
            await asyncio.sleep(HOLD_SECONDS)
            await uow.commit()
            return granted

    async def second() -> bool:
        await first_reserved.wait()
        async with SqlAlchemyUnitOfWork(sessions) as uow:
            granted = await uow.products.reserve_stock(variant_id, quantity)
            await uow.commit()
            return granted

    return tuple(await asyncio.gather(first(), second()))  # type: ignore[return-value]


async def test_the_last_unit_is_sold_once_when_two_checkouts_race(engine: AsyncEngine) -> None:
    variant_id = await _seed_variant(engine, stock=1)

    granted = await _race(engine, variant_id, quantity=1)

    assert sorted(granted) == [False, True], f"both checkouts were granted: {granted}"
    assert await _reserved(engine, variant_id) == 1


async def test_concurrent_reservations_that_fit_are_both_counted(engine: AsyncEngine) -> None:
    """No lost update: two grants of 2 from 5 leave 4 reserved, not 2."""
    variant_id = await _seed_variant(engine, stock=5)

    granted = await _race(engine, variant_id, quantity=2)

    assert granted == (True, True)
    assert await _reserved(engine, variant_id) == 4


async def test_a_reservation_beyond_what_is_left_is_refused(engine: AsyncEngine) -> None:
    variant_id = await _seed_variant(engine, stock=3)
    async with SqlAlchemyUnitOfWork(build_sessionmaker(engine)) as uow:
        assert await uow.products.reserve_stock(variant_id, 2) is True
        assert await uow.products.reserve_stock(variant_id, 2) is False
        assert await uow.products.reserve_stock(variant_id, 1) is True
        await uow.commit()

    assert await _reserved(engine, variant_id) == 3
