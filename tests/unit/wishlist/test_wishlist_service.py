"""WishlistService behaviour — proved against in-memory repositories."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domains.products.domain.entities import Category, Product, ProductImage
from app.domains.products.domain.repositories import AbstractProductRepository
from app.domains.wishlist.application.service import WishlistService
from app.domains.wishlist.domain.entities import Wishlist
from app.domains.wishlist.domain.repositories import AbstractWishlistRepository
from app.shared.exceptions import NotFoundError


class InMemoryWishlistRepository(AbstractWishlistRepository):
    def __init__(self) -> None:
        self._store: dict[int, Wishlist] = {}
        self._next = 1

    async def add(self, wishlist: Wishlist) -> Wishlist:
        wishlist.id = self._next
        self._next += 1
        self._store[wishlist.id] = wishlist
        return wishlist

    async def get_by_user_id(self, user_id: int) -> Wishlist | None:
        return next((w for w in self._store.values() if w.user_id == user_id), None)

    async def save(self, wishlist: Wishlist) -> Wishlist:
        self._store[wishlist.id] = wishlist
        return wishlist


class InMemoryProductRepository(AbstractProductRepository):
    def __init__(self, products: list[Product]) -> None:
        self._products = products

    async def add(self, product: Product) -> Product:  # pragma: no cover - unused
        raise NotImplementedError

    async def get_by_id(self, product_id: int) -> Product | None:  # pragma: no cover
        raise NotImplementedError

    async def get_by_slug(self, slug: str) -> Product | None:
        return next((p for p in self._products if p.slug == slug), None)

    async def list_active(self, *, limit: int, offset: int) -> list[Product]:  # pragma: no cover
        raise NotImplementedError

    async def count_active(self) -> int:  # pragma: no cover
        raise NotImplementedError

    async def save(self, product: Product) -> Product | None:  # pragma: no cover
        raise NotImplementedError

    async def reserve_stock(self, variant_id: int, quantity: int) -> bool:  # pragma: no cover
        raise NotImplementedError


def _product(slug: str = "alpha", *, active: bool = True) -> Product:
    return Product(
        id=1,
        slug=slug,
        name=f"Product {slug}",
        category=Category(id=1, name="Curated", slug="curated"),
        price=Decimal("42000.00"),
        images=[ProductImage(url="/a.jpg", view="front")],
        is_active=active,
    )


def _service(*products: Product) -> tuple[WishlistService, InMemoryWishlistRepository]:
    wishlists = InMemoryWishlistRepository()
    repo = InMemoryProductRepository(list(products) or [_product()])
    return WishlistService(wishlists=wishlists, products=repo), wishlists


async def test_add_snapshots_product_details() -> None:
    service, _ = _service()

    wishlist = await service.add(user_id=1, product_slug="alpha")

    assert wishlist.count == 1
    item = wishlist.items[0]
    assert item.product_slug == "alpha"
    assert item.product_name == "Product alpha"
    assert item.unit_price == Decimal("42000.00")
    assert item.image == "/a.jpg"


async def test_add_is_idempotent() -> None:
    service, _ = _service()
    await service.add(user_id=1, product_slug="alpha")

    again = await service.add(user_id=1, product_slug="alpha")

    assert again.count == 1


async def test_add_unknown_product_raises() -> None:
    service, _ = _service()

    with pytest.raises(NotFoundError):
        await service.add(user_id=1, product_slug="ghost")


async def test_add_inactive_product_raises() -> None:
    service, _ = _service(_product("gone", active=False))

    with pytest.raises(NotFoundError):
        await service.add(user_id=1, product_slug="gone")


async def test_remove_present_item() -> None:
    service, _ = _service()
    await service.add(user_id=1, product_slug="alpha")

    wishlist = await service.remove(user_id=1, product_slug="alpha")

    assert wishlist.count == 0


async def test_remove_absent_item_raises() -> None:
    service, _ = _service()

    with pytest.raises(NotFoundError):
        await service.remove(user_id=1, product_slug="alpha")


async def test_list_is_empty_without_creating() -> None:
    service, wishlists = _service()

    wishlist = await service.list(user_id=99)

    assert wishlist.count == 0
    assert wishlists._store == {}  # a read must not persist an empty wishlist


async def test_users_have_separate_wishlists() -> None:
    service, _ = _service()

    await service.add(user_id=1, product_slug="alpha")
    other = await service.list(user_id=2)

    assert other.count == 0
