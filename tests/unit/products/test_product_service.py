"""ProductService catalog reads — proved against in-memory repositories."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domains.products.application.service import ProductService
from app.domains.products.domain.entities import (
    Category,
    Inventory,
    Product,
    ProductImage,
    ProductVariant,
)
from app.domains.products.domain.repositories import (
    AbstractCategoryRepository,
    AbstractProductRepository,
)
from app.shared.exceptions import NotFoundError
from app.shared.pagination import PaginationParams


class InMemoryProductRepository(AbstractProductRepository):
    def __init__(self) -> None:
        self._by_id: dict[int, Product] = {}
        self._next = 1

    async def add(self, product: Product) -> Product:
        product.id = self._next
        self._by_id[product.id] = product
        self._next += 1
        return product

    async def get_by_id(self, product_id: int) -> Product | None:
        found = self._by_id.get(product_id)
        return found if found and found.is_active else None

    async def get_by_slug(self, slug: str) -> Product | None:
        for product in self._by_id.values():
            if product.slug == slug and product.is_active:
                return product
        return None

    async def list_active(self, *, limit: int, offset: int) -> list[Product]:
        active = [p for p in self._by_id.values() if p.is_active]
        return active[offset : offset + limit]

    async def count_active(self) -> int:
        return sum(1 for p in self._by_id.values() if p.is_active)

    async def save(self, product: Product) -> Product | None:
        # Products are held by reference, so editing one edits the store; only a
        # product that is really in it can come back out.
        return self._by_id.get(product.id)

    async def reserve_stock(self, variant_id: int, quantity: int) -> bool:
        for product in self._by_id.values():
            for variant in product.variants:
                if variant.id == variant_id:
                    if variant.inventory.available < quantity:
                        return False
                    variant.inventory.reserved += quantity
                    return True
        return False


class InMemoryCategoryRepository(AbstractCategoryRepository):
    def __init__(self) -> None:
        self._items: list[Category] = []
        self._next = 1

    async def add(self, category: Category) -> Category:
        stored = Category(id=self._next, name=category.name, slug=category.slug)
        self._next += 1
        self._items.append(stored)
        return stored

    async def list(self) -> list[Category]:
        return list(self._items)


def _product(slug: str, category: Category, *, active: bool = True) -> Product:
    return Product(
        id=0,
        slug=slug,
        name=f"Product {slug}",
        category=category,
        price=Decimal("1000.00"),
        images=[ProductImage(url="/i.jpg", view="front")],
        variants=[
            ProductVariant(id=1, sku=f"{slug}-M", size="M", inventory=Inventory(quantity=5))
        ],
        is_active=active,
    )


async def _seed() -> tuple[InMemoryProductRepository, Category, ProductService]:
    products = InMemoryProductRepository()
    categories = InMemoryCategoryRepository()
    category = await categories.add(Category(id=0, name="Curated", slug="curated"))
    await products.add(_product("alpha", category))
    await products.add(_product("beta", category))
    await products.add(_product("gone", category, active=False))
    return products, category, ProductService(products, categories)


async def test_list_products_returns_only_active_page() -> None:
    _, _, service = await _seed()

    page = await service.list_products(PaginationParams(page=1, page_size=20))

    assert page.total == 2
    assert {p.slug for p in page.items} == {"alpha", "beta"}


async def test_get_product_by_slug() -> None:
    _, _, service = await _seed()

    product = await service.get_product("alpha")

    assert product.slug == "alpha"


async def test_get_product_by_numeric_id() -> None:
    _, _, service = await _seed()

    product = await service.get_product("1")

    assert product.slug == "alpha"


async def test_get_product_unknown_raises_not_found() -> None:
    _, _, service = await _seed()

    with pytest.raises(NotFoundError):
        await service.get_product("missing")


async def test_inactive_product_is_not_found() -> None:
    _, _, service = await _seed()

    with pytest.raises(NotFoundError):
        await service.get_product("gone")


async def test_list_categories() -> None:
    _, category, service = await _seed()

    categories = await service.list_categories()

    assert [c.slug for c in categories] == [category.slug]
