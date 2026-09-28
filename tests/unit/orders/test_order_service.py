"""Unit tests for the checkout orchestration with in-memory fakes.

These pin the Phase 09 contract: a cart only becomes an order after cart,
inventory and pricing validation, the order lands in ``PENDING_PAYMENT``, and no
payment provider is involved anywhere.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domains.cart.domain.entities import Cart, CartItem
from app.domains.cart.domain.repositories import AbstractCartRepository
from app.domains.orders.application.service import (
    CheckoutCommand,
    OrderService,
    new_order_reference,
)
from app.domains.orders.domain.entities import Order
from app.domains.orders.domain.enums import OrderStatus
from app.domains.orders.domain.repositories import AbstractOrderRepository
from app.domains.products.domain.entities import (
    Category,
    Inventory,
    Product,
    ProductImage,
    ProductVariant,
)
from app.domains.products.domain.repositories import AbstractProductRepository
from app.shared.exceptions import ConflictError, NotFoundError, ValidationError

USER_ID = 7
PRICE = Decimal("58500.00")


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


class InMemoryOrderRepository(AbstractOrderRepository):
    def __init__(self) -> None:
        self._store: dict[int, Order] = {}
        self._next = 1

    async def add(self, order: Order) -> Order:
        order.id = self._next
        self._next += 1
        for index, item in enumerate(order.items, start=1):
            item.id = index
        self._store[order.id] = order
        return order

    async def get_by_id(self, order_id: int) -> Order | None:
        return self._store.get(order_id)

    async def list_by_user_id(self, user_id: int) -> list[Order]:
        return [o for o in self._store.values() if o.user_id == user_id]

    async def list_all(self, *, limit: int, offset: int) -> list[Order]:  # pragma: no cover
        return list(self._store.values())[offset : offset + limit]

    async def count_all(self, *, status: OrderStatus | None = None) -> int:  # pragma: no cover
        return sum(1 for o in self._store.values() if status is None or o.status is status)

    async def save(self, order: Order) -> Order:  # pragma: no cover - unused here
        # The orders domain never rewrites an order; confirming a payment does.
        self._store[order.id] = order
        return order


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

    async def reserve_stock(self, variant_id: int, quantity: int) -> bool:
        for product in self._products:
            for variant in product.variants:
                if variant.id == variant_id:
                    if variant.inventory.available < quantity:
                        return False
                    variant.inventory.reserved += quantity
                    return True
        return False


def _product(*, price: Decimal = PRICE, stock: int = 10, active: bool = True) -> Product:
    return Product(
        id=1,
        slug="alpha",
        name="Alpha Jersey",
        category=Category(id=1, name="Curated", slug="curated"),
        price=price,
        images=[ProductImage(url="/front.jpg", view="front")],
        variants=[
            ProductVariant(id=11, sku="alpha-M", size="M", inventory=Inventory(quantity=stock)),
            ProductVariant(id=12, sku="alpha-L", size="L", inventory=Inventory(quantity=stock)),
        ],
        is_active=active,
    )


def _cart(items: list[CartItem] | None = None) -> Cart:
    if items is None:
        items = [
            CartItem(
                id=1,
                variant_id=11,
                product_slug="alpha",
                product_name="Alpha Jersey",
                size="M",
                quantity=2,
                unit_price=PRICE,
            )
        ]
    return Cart(id=1, user_id=USER_ID, items=items)


def _checkout(**overrides: object) -> CheckoutCommand:
    kwargs: dict = {
        "contact_name": "Ada Zoid",
        "contact_email": "ada@example.com",
        "contact_phone": "+234 800 000 0000",
        "address_line": "12 Concrete Road",
        "city_state": "Lagos State",
    }
    kwargs.update(overrides)
    return CheckoutCommand(**kwargs)  # type: ignore[arg-type]


def _service(
    *,
    cart: Cart | None,
    product: Product | None = None,
) -> tuple[OrderService, InMemoryOrderRepository, InMemoryCartRepository, list[Product]]:
    products = [product] if product is not None else [_product()]
    carts = InMemoryCartRepository()
    if cart is not None:
        carts._store[cart.id] = cart
    orders = InMemoryOrderRepository()
    service = OrderService(
        orders=orders, carts=carts, products=InMemoryProductRepository(products)
    )
    return service, orders, carts, products


async def test_valid_cart_becomes_pending_payment_order() -> None:
    product = _product()
    service, orders, carts, _ = _service(cart=_cart(), product=product)

    order = await service.create_from_cart(user_id=USER_ID, checkout=_checkout())

    assert order.id != 0
    assert order.status is OrderStatus.PENDING_PAYMENT
    assert order.user_id == USER_ID
    assert order.total == PRICE * 2
    assert order.item_count == 2
    assert order.reference.startswith("ZD-")
    line = order.items[0]
    assert (line.product_slug, line.size, line.quantity) == ("alpha", "M", 2)
    # The order is a snapshot, not a live view of the catalog.
    assert line.product_name == "Alpha Jersey"
    # Stock was reserved for exactly the ordered quantity...
    assert product.variants[0].inventory.reserved == 2
    # ...and the cart has been consumed.
    assert await carts.get_by_user_id(USER_ID) is None


async def test_order_reference_is_unique() -> None:
    references = {new_order_reference() for _ in range(200)}

    assert len(references) == 200


async def test_missing_cart_is_rejected() -> None:
    service, orders, _, _ = _service(cart=None)

    with pytest.raises(ValidationError):
        await service.create_from_cart(user_id=USER_ID, checkout=_checkout())

    assert orders._store == {}


async def test_empty_cart_is_rejected() -> None:
    service, _, _, _ = _service(cart=_cart(items=[]))

    with pytest.raises(ValidationError):
        await service.create_from_cart(user_id=USER_ID, checkout=_checkout())


async def test_inventory_validation_failure_blocks_order() -> None:
    product = _product(stock=1)
    service, orders, carts, _ = _service(cart=_cart(), product=product)

    with pytest.raises(ConflictError):
        await service.create_from_cart(user_id=USER_ID, checkout=_checkout())

    assert orders._store == {}
    # The cart survives a failed checkout so the customer can fix it.
    assert await carts.get_by_user_id(USER_ID) is not None
    assert product.variants[0].inventory.reserved == 0


async def test_pricing_validation_failure_blocks_order() -> None:
    # The catalog price moved after the line was added to the cart.
    product = _product(price=Decimal("61000.00"))
    service, orders, _, _ = _service(cart=_cart(), product=product)

    with pytest.raises(ConflictError):
        await service.create_from_cart(user_id=USER_ID, checkout=_checkout())

    assert orders._store == {}


async def test_withdrawn_product_is_rejected() -> None:
    service, orders, _, _ = _service(cart=_cart(), product=_product(active=False))

    with pytest.raises(ValidationError):
        await service.create_from_cart(user_id=USER_ID, checkout=_checkout())

    assert orders._store == {}


async def test_removed_size_is_rejected() -> None:
    cart = _cart()
    cart.items[0].variant_id = 99
    service, orders, _, _ = _service(cart=cart)

    with pytest.raises(ValidationError):
        await service.create_from_cart(user_id=USER_ID, checkout=_checkout())

    assert orders._store == {}


async def test_order_is_only_readable_by_its_owner() -> None:
    service, _, _, _ = _service(cart=_cart())
    order = await service.create_from_cart(user_id=USER_ID, checkout=_checkout())

    mine = await service.get_for_user(user_id=USER_ID, order_id=order.id)
    assert mine.reference == order.reference

    with pytest.raises(NotFoundError):
        await service.get_for_user(user_id=USER_ID + 1, order_id=order.id)

    with pytest.raises(NotFoundError):
        await service.get_for_user(user_id=USER_ID, order_id=4242)


async def test_list_is_scoped_to_the_caller() -> None:
    service, _, _, _ = _service(cart=_cart())
    placed = await service.create_from_cart(user_id=USER_ID, checkout=_checkout())

    mine = await service.list_for_user(user_id=USER_ID)
    assert [order.id for order in mine] == [placed.id]

    assert await service.list_for_user(user_id=USER_ID + 1) == []
