"""Products application service — public catalog reads.

Depends only on repository contracts. Deliberately read-only: admin product
mutation is a separate capability (Phase 15) and is not exposed here.

Search, filtering and ordering are catalog rules in ``products.domain.search``;
this service reads the catalog once and applies them, then pages the result, so
a fuzzy query and a plain listing page the same way.
"""

from __future__ import annotations

from app.domains.products.domain.entities import Category, Product
from app.domains.products.domain.repositories import (
    AbstractCategoryRepository,
    AbstractProductRepository,
)
from app.domains.products.domain.search import ProductCriteria, search
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

    async def list_products(
        self,
        params: PaginationParams,
        criteria: ProductCriteria | None = None,
    ) -> Page[Product]:
        """A page of active products, optionally searched, filtered and ordered."""
        matches = search(await self._products.list_catalog(), criteria or ProductCriteria())
        return Page(
            items=matches[params.offset : params.offset + params.limit],
            page=params.page,
            page_size=params.page_size,
            total=len(matches),
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
