"""Products application service — public catalog reads.

Depends only on repository contracts. Deliberately read-only: admin product
mutation is a separate capability (Phase 15) and is not exposed here.
"""

from __future__ import annotations

from app.domains.products.domain.entities import Category, Product
from app.domains.products.domain.repositories import (
    AbstractCategoryRepository,
    AbstractProductRepository,
)
from app.shared.exceptions import NotFoundError
from app.shared.pagination import Page, PaginationParams


class ProductService:
    def __init__(
        self,
        products: AbstractProductRepository,
        categories: AbstractCategoryRepository,
    ) -> None:
        self._products = products
        self._categories = categories

    async def list_products(self, params: PaginationParams) -> Page[Product]:
        items = await self._products.list_active(limit=params.limit, offset=params.offset)
        total = await self._products.count_active()
        return Page(
            items=items,
            page=params.page,
            page_size=params.page_size,
            total=total,
        )

    async def get_product(self, identifier: str) -> Product:
        """Resolve a product by numeric id or public slug (slug is the identity
        the storefront navigates by)."""
        product: Product | None = None
        if identifier.isdigit():
            product = await self._products.get_by_id(int(identifier))
        if product is None:
            product = await self._products.get_by_slug(identifier)
        if product is None:
            raise NotFoundError("Product not found.")
        return product

    async def list_categories(self) -> list[Category]:
        return await self._categories.list()
