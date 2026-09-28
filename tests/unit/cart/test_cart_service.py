"""CartService orchestration — proved against in-memory repositories.

These exercise the defined contract only: cart creation for guest/authenticated
shoppers, product resolution and snapshotting on add, item mutation, and that
merge is callable through the service boundary via an injectable strategy. The
duplicate/conflict semantics of merge are Not Specified and intentionally not
asserted here (see ``app/domains/cart/application/merge.py``).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domains.cart.application.merge import AbstractCartMergeStrategy
from app.domains.cart.application.service import CartService
from app.domains.cart.domain.entities import Cart
from app.domains.cart.domain.repositories import AbstractCartRepository
from app.domains.products.domain.entities import (
    Category,
    Inventory,
    Product,
    ProductImage,
    ProductVariant,
)
from app.domains.products.domain.repositories import AbstractProductRepository
from app.shared.exceptions import NotFoundError, ValidationError


class InMemoryCartRepository(AbstractCartRepository):
    def __init__(self) -> None:
        self._store: dict[int, Cart] = {}
        self._next = 1

    async def add(self, cart: Cart) -> Cart:
        cart.id = self._next
        self._next += 1
        self._store[cart.id] = cart
        return cart

    async def get_by_id(self, cart_id: int) -> Cart | None:
        return self._store.get(cart_id)

    async def get_by_user_id(self, user_id: int) -> Cart | None:
        return next((c for c in self._store.values() if c.user_id == user_id), None)

    async def get_by_guest_token(self, guest_token: str) -> Cart | None:
        return next((c for c in self._store.values() if c.guest_token == guest_token), None)

    async def save(self, cart: Cart) -> Cart:
        self._store[cart.id] = cart
        return cart

    async def delete(self, cart: Cart) -> None:
        self._store.pop(cart.id, None)


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


def _product() -> Product:
    category = Category(id=1, name="Curated", slug="curated")
    return Product(
        id=1,
        slug="alpha",
        name="Alpha Jersey",
        category=category,
        price=Decimal("58500.00"),
        images=[ProductImage(url="/front.jpg", view="front")],
        variants=[
            ProductVariant(id=11, sku="alpha-M", size="M", inventory=Inventory(quantity=10)),
            ProductVariant(id=12, sku="alpha-L", size="L", inventory=Inventory(quantity=10)),
        ],
    )


def _service(**kwargs: object) -> tuple[CartService, InMemoryCartRepository]:
    carts = InMemoryCartRepository()
    products = InMemoryProductRepository([_product()])
    service = CartService(carts=carts, products=products, **kwargs)  # type: ignore[arg-type]
    return service, carts


async def test_ensure_guest_cart_issues_token() -> None:
    service, carts = _service()

    cart = await service.ensure_cart(user_id=None, guest_token=None)

    assert cart.guest_token
    assert cart.user_id is None
    assert cart.id in carts._store


async def test_ensure_reuses_existing_guest_cart() -> None:
    service, _ = _service()
    first = await service.ensure_cart(user_id=None, guest_token=None)

    second = await service.ensure_cart(user_id=None, guest_token=first.guest_token)

    assert second.id == first.id


async def test_ensure_authenticated_cart() -> None:
    service, _ = _service()

    cart = await service.ensure_cart(user_id=42, guest_token=None)

    assert cart.user_id == 42
    assert cart.guest_token is None


async def test_add_item_snapshots_product_details() -> None:
    service, _ = _service()
    cart = await service.ensure_cart(user_id=None, guest_token=None)

    cart = await service.add_item(cart, product_slug="alpha", size="M", quantity=2)

    assert cart.count == 2
    item = cart.items[0]
    assert item.variant_id == 11
    assert item.product_name == "Alpha Jersey"
    assert item.unit_price == Decimal("58500.00")
    assert item.image == "/front.jpg"
    assert cart.total == Decimal("117000.00")


async def test_add_item_unknown_product_raises() -> None:
    service, _ = _service()
    cart = await service.ensure_cart(user_id=None, guest_token=None)

    with pytest.raises(NotFoundError):
        await service.add_item(cart, product_slug="nope", size="M", quantity=1)


async def test_add_item_unavailable_size_raises() -> None:
    service, _ = _service()
    cart = await service.ensure_cart(user_id=None, guest_token=None)

    with pytest.raises(ValidationError):
        await service.add_item(cart, product_slug="alpha", size="XXL", quantity=1)


async def test_update_and_remove_item() -> None:
    service, _ = _service()
    cart = await service.ensure_cart(user_id=None, guest_token=None)
    cart = await service.add_item(cart, product_slug="alpha", size="M", quantity=1)
    item_id = cart.items[0].id

    cart = await service.update_item(cart, item_id, 5)
    assert cart.items[0].quantity == 5

    cart = await service.remove_item(cart, item_id)
    assert cart.items == []


async def test_merge_folds_guest_cart_into_user_and_removes_guest() -> None:
    service, carts = _service()
    guest = await service.ensure_cart(user_id=None, guest_token=None)
    guest = await service.add_item(guest, product_slug="alpha", size="M", quantity=3)
    guest_token = guest.guest_token

    merged = await service.merge_guest_into_user(user_id=7, guest_token=guest_token)

    assert merged.user_id == 7
    assert merged.count == 3
    assert await carts.get_by_guest_token(guest_token) is None  # guest cart gone


class _RecordingMergeStrategy(AbstractCartMergeStrategy):
    def __init__(self) -> None:
        self.calls = 0

    def merge(self, target: Cart, source: Cart) -> None:
        self.calls += 1
        for item in list(source.items):
            item.id = 0
            target.add_item(item)


async def test_merge_uses_injected_strategy() -> None:
    strategy = _RecordingMergeStrategy()
    service, _ = _service(merge_strategy=strategy)
    guest = await service.ensure_cart(user_id=None, guest_token=None)
    guest = await service.add_item(guest, product_slug="alpha", size="L", quantity=1)

    await service.merge_guest_into_user(user_id=9, guest_token=guest.guest_token)

    assert strategy.calls == 1
