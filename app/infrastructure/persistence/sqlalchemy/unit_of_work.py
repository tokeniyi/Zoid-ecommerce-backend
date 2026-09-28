"""Unit of Work — the transactional boundary for write use-cases.

`AbstractUnitOfWork` is the framework-free contract application services depend
on. `SqlAlchemyUnitOfWork` is the concrete implementation; repositories are
attached to it in later phases as domains are introduced.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domains.auth.domain.repositories import AbstractCredentialsRepository
from app.domains.cart.domain.repositories import AbstractCartRepository
from app.domains.orders.domain.repositories import AbstractOrderRepository
from app.domains.payments.domain.repositories import (
    AbstractRefundRepository,
    AbstractTransactionRepository,
    AbstractWebhookEventRepository,
)
from app.domains.products.domain.repositories import (
    AbstractCategoryRepository,
    AbstractProductRepository,
)
from app.domains.users.domain.repositories import AbstractUserRepository
from app.domains.wishlist.domain.repositories import AbstractWishlistRepository
from app.infrastructure.persistence.sqlalchemy.repositories import (
    SqlCartRepository,
    SqlCategoryRepository,
    SqlCredentialsRepository,
    SqlOrderRepository,
    SqlProductRepository,
    SqlRefundRepository,
    SqlTransactionRepository,
    SqlUserRepository,
    SqlWebhookEventRepository,
    SqlWishlistRepository,
)


class AbstractUnitOfWork:
    """Contract for a transactional unit of work.

    A framework-free marker that application services depend on. Repositories
    are declared here and instantiated by the concrete implementation as
    domains land (more are added in later phases: products, cart, orders,
    payments).
    """

    users: AbstractUserRepository
    credentials: AbstractCredentialsRepository
    products: AbstractProductRepository
    categories: AbstractCategoryRepository
    carts: AbstractCartRepository
    wishlists: AbstractWishlistRepository
    orders: AbstractOrderRepository
    transactions: AbstractTransactionRepository
    refunds: AbstractRefundRepository
    webhook_events: AbstractWebhookEventRepository


class SqlAlchemyUnitOfWork(AbstractUnitOfWork):
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker
        self.session: AsyncSession

    async def __aenter__(self) -> Self:
        self.session = self._sessionmaker()
        # Begin an explicit transaction so commit/rollback are well defined.
        await self.session.begin()
        self.users = SqlUserRepository(self.session)
        self.credentials = SqlCredentialsRepository(self.session)
        self.products = SqlProductRepository(self.session)
        self.categories = SqlCategoryRepository(self.session)
        self.carts = SqlCartRepository(self.session)
        self.wishlists = SqlWishlistRepository(self.session)
        self.orders = SqlOrderRepository(self.session)
        self.transactions = SqlTransactionRepository(self.session)
        self.refunds = SqlRefundRepository(self.session)
        self.webhook_events = SqlWebhookEventRepository(self.session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            await self.session.rollback()
        await self.session.close()

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()


@asynccontextmanager
async def unit_of_work(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[SqlAlchemyUnitOfWork]:
    """Convenience context manager yielding a begun Unit of Work."""
    uow = SqlAlchemyUnitOfWork(sessionmaker)
    async with uow:
        yield uow
