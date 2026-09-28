"""Persistence contracts for the products domain."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domains.products.domain.entities import Category, Product


class AbstractProductRepository(ABC):
    """Read/write the product catalog."""

    @abstractmethod
    async def add(self, product: Product) -> Product:
        """Persist a new product (with images/variants/inventory) and return it."""

    @abstractmethod
    async def get_by_id(self, product_id: int) -> Product | None:
        """Return the product with ``product_id`` or ``None``."""

    @abstractmethod
    async def get_by_slug(self, slug: str) -> Product | None:
        """Return the product with ``slug`` or ``None``."""

    @abstractmethod
    async def list_active(self, *, limit: int, offset: int) -> list[Product]:
        """Return a page of active products."""

    @abstractmethod
    async def count_active(self) -> int:
        """Total number of active products."""

    @abstractmethod
    async def save(self, product: Product) -> Product | None:
        """Persist changes made to a loaded product; ``None`` if it is gone.

        The admin surface edits a product through its entity, so this is the door
        those edits leave through. It writes the product's own fields and the
        ``quantity`` of each existing variant's inventory, matched by variant id.
        It never creates or removes variants or images, and never writes a
        reservation (those belong to the checkout path in :meth:`reserve_stock`).
        """

    @abstractmethod
    async def reserve_stock(self, variant_id: int, quantity: int) -> bool:
        """Reserve ``quantity`` units of a variant.

        Returns ``False`` (and reserves nothing) when fewer units are available
        than requested; otherwise increases the variant's reserved count.
        """


class AbstractCategoryRepository(ABC):
    """Read/write catalog categories."""

    @abstractmethod
    async def add(self, category: Category) -> Category:
        """Persist a new category and return it with its generated id."""

    @abstractmethod
    async def list(self) -> list[Category]:
        """Return all categories."""
