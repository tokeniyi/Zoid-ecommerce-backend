"""AdminService use-cases — proved against in-memory repositories.

No database and no HTTP here: what is being pinned is that the shop side of the
store runs through the *same* contracts and the *same* rules as the customer side
— the dashboard reads the real aggregates, an edit is checked by the product
itself, and a restock obeys the inventory rule rather than a copy of it written
beside it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domains.admin.application.service import (
    AdminService,
    NewImage,
    NewProductCommand,
    NewSize,
    RestockCommand,
)
from app.domains.orders.domain.entities import Order, OrderItem
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
from app.domains.users.domain.entities import User
from app.domains.users.domain.repositories import AbstractUserRepository
from app.shared.exceptions import ConflictError, NotFoundError, ValidationError
from app.shared.pagination import PaginationParams

CATEGORY = Category(id=1, name="Curated Jersey", slug="curated-jersey")


class FakeProductRepository(AbstractProductRepository):
    """Holds products by reference, like a session holding loaded rows."""

    def __init__(self) -> None:
        self._by_id: dict[int, Product] = {}
        self._next = 1
        self.saved: list[int] = []
        self.listed: list[tuple[int, int]] = []

    async def add(self, product: Product) -> Product:
        product.id = self._next
        self._by_id[product.id] = product
        self._next += 1
        return product

    async def get_by_id(self, product_id: int) -> Product | None:
        # Like the real catalog read: a hidden product is still a product.
        return self._by_id.get(product_id)

    async def get_by_slug(self, slug: str) -> Product | None:
        return next((p for p in self._by_id.values() if p.slug == slug), None)

    async def list_active(self, *, limit: int, offset: int) -> list[Product]:
        self.listed.append((limit, offset))
        active = [p for p in self._by_id.values() if p.is_active]
        return active[offset : offset + limit]

    async def count_active(self) -> int:
        return sum(1 for p in self._by_id.values() if p.is_active)

    async def save(self, product: Product) -> Product | None:
        self.saved.append(product.id)
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


class FakeOrderRepository(AbstractOrderRepository):
    def __init__(self) -> None:
        self._by_id: dict[int, Order] = {}
        self._next = 1
        self.listed: list[tuple[int, int]] = []

    async def add(self, order: Order) -> Order:
        order.id = self._next
        self._by_id[order.id] = order
        self._next += 1
        return order

    async def get_by_id(self, order_id: int) -> Order | None:
        return self._by_id.get(order_id)

    async def list_by_user_id(self, user_id: int) -> list[Order]:
        return [o for o in self._by_id.values() if o.user_id == user_id]

    async def list_all(self, *, limit: int, offset: int) -> list[Order]:
        self.listed.append((limit, offset))
        newest_first = sorted(self._by_id.values(), key=lambda o: o.id, reverse=True)
        return newest_first[offset : offset + limit]

    async def count_all(self, *, status: OrderStatus | None = None) -> int:
        return sum(1 for o in self._by_id.values() if status is None or o.status is status)

    async def save(self, order: Order) -> Order:
        self._by_id[order.id] = order
        return order


class FakeUserRepository(AbstractUserRepository):
    def __init__(self) -> None:
        self._by_id: dict[int, User] = {}
        self._next = 1
        self.listed: list[tuple[int, int]] = []

    async def add(self, user: User) -> User:
        user.id = self._next
        self._by_id[user.id] = user
        self._next += 1
        return user

    async def get_by_id(self, user_id: int) -> User | None:
        return self._by_id.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        return next((u for u in self._by_id.values() if u.email == email), None)

    async def list_all(self, *, limit: int, offset: int) -> list[User]:
        self.listed.append((limit, offset))
        return list(self._by_id.values())[offset : offset + limit]

    async def count_all(self) -> int:
        return len(self._by_id)

    async def update_profile(
        self,
        user_id: int,
        *,
        name: str | None = None,
        phone: str | None = None,
    ) -> User | None:
        user = self._by_id.get(user_id)
        if user is None:
            return None
        if name is not None:
            user.name = name
        if phone is not None:
            user.phone = phone
        return user


def _product(
    slug: str,
    *,
    price: Decimal = Decimal("1000.00"),
    stock: dict[str, int] | None = None,
    reserved: dict[str, int] | None = None,
    active: bool = True,
    is_bestseller: bool = False,
    is_special: bool = False,
) -> Product:
    stock = stock or {}
    reserved = reserved or {}
    return Product(
        id=0,
        slug=slug,
        name=f"Jersey {slug}",
        category=CATEGORY,
        price=price,
        images=[ProductImage(url=f"/{slug}.jpg", view="front")],
        variants=[
            ProductVariant(
                id=index,
                sku=f"{slug}-{size}",
                size=size,
                inventory=Inventory(quantity=units, reserved=reserved.get(size, 0)),
            )
            for index, (size, units) in enumerate(stock.items(), start=1)
        ],
        is_active=active,
        is_bestseller=is_bestseller,
        is_special=is_special,
    )


def _order(*, status: OrderStatus = OrderStatus.PENDING_PAYMENT) -> Order:
    return Order(
        id=0,
        reference=f"ZD-{status.value[:3]}-1",
        user_id=1,
        status=status,
        contact_name="Ada Zoid",
        contact_email="ada@example.com",
        address_line="12 Concrete Road",
        items=[
            OrderItem(
                id=0,
                variant_id=1,
                product_slug="alpha",
                product_name="Jersey alpha",
                size="M",
                quantity=1,
                unit_price=Decimal("1000.00"),
            )
        ],
    )


def _service() -> (
    tuple[AdminService, FakeProductRepository, FakeOrderRepository, FakeUserRepository]
):
    products, orders, users = (
        FakeProductRepository(),
        FakeOrderRepository(),
        FakeUserRepository(),
    )
    return (
        AdminService(products=products, orders=orders, users=users),
        products,
        orders,
        users,
    )


def _command(**overrides: object) -> NewProductCommand:
    base: dict[str, object] = {
        "slug": "new-jersey",
        "name": "New Jersey",
        "category_slug": "curated-jersey",
        "category_name": "Curated Jersey",
        "price": Decimal("55000.00"),
        "sizes": (NewSize(size="M", quantity=4), NewSize(size="L", quantity=0)),
        "images": (NewImage(url="/new.jpg", view="front"),),
    }
    base.update(overrides)
    return NewProductCommand(**base)  # type: ignore[arg-type]


# ── Dashboard ────────────────────────────────────────────────────────


async def test_dashboard_counts_the_catalog_it_can_actually_sell() -> None:
    service, products, orders, users = _service()
    await products.add(_product("plenty", stock={"M": 50}))
    await products.add(
        _product("thin", price=Decimal("2000.00"), stock={"M": 3}, is_bestseller=True)
    )
    await products.add(_product("sold-out", stock={"M": 0}, is_special=True))
    await orders.add(_order())
    await orders.add(_order(status=OrderStatus.PAID))
    await users.add(User(id=0, email="ada@example.com", name="Ada"))

    overview = await service.dashboard()

    assert overview.catalog.products == 3
    assert overview.catalog.units_available == 53
    # 50 x 1000 + 3 x 2000: what is sitting on the shelves, priced.
    assert overview.catalog.inventory_value == Decimal("56000.00")
    assert (overview.catalog.out_of_stock, overview.catalog.low_stock) == (1, 1)
    assert (overview.catalog.bestsellers, overview.catalog.specials) == (1, 1)
    assert (overview.orders.total, overview.orders.paid) == (2, 1)
    assert overview.orders.awaiting_payment == 1
    assert overview.customers.total == 1


async def test_a_hidden_product_is_not_stock_the_shop_is_holding() -> None:
    service, products, _, _ = _service()
    await products.add(_product("retired", stock={"M": 99}, active=False))

    overview = await service.dashboard()

    assert overview.catalog.products == 0
    assert overview.catalog.units_available == 0


async def test_restocking_need_is_the_urgent_half_of_running_low() -> None:
    service, products, _, _ = _service()
    await products.add(_product("thin", stock={"M": 3}))
    await products.add(_product("sold-out", stock={"M": 0}))
    await products.add(_product("plenty", stock={"M": 50}))

    overview = await service.dashboard()

    assert overview.needs_restocking == 2


async def test_reserved_units_are_not_counted_as_stock_on_the_shelf() -> None:
    service, products, _, _ = _service()
    # Six made, two already promised to someone who has not paid yet.
    await products.add(_product("half-gone", stock={"M": 6}, reserved={"M": 2}))

    overview = await service.dashboard()

    assert overview.catalog.units_available == 4
    assert overview.catalog.low_stock == 1


async def test_the_dashboard_walks_the_catalog_a_page_at_a_time() -> None:
    service, products, _, _ = _service()
    for index in range(3):
        await products.add(_product(f"p{index}", stock={"M": 10}))

    await service.dashboard()

    assert products.listed == [(100, 0)]


# ── Reads over the ledgers ───────────────────────────────────────────


async def test_admin_orders_are_paged_by_the_repository_that_owns_the_order() -> None:
    service, _, orders, _ = _service()
    await orders.add(_order())
    await orders.add(_order(status=OrderStatus.PAID))

    page = await service.list_orders(PaginationParams(page=1, page_size=1))

    assert (page.total, page.total_pages) == (2, 2)
    assert [order.status for order in page.items] == [OrderStatus.PAID]
    assert orders.listed == [(1, 0)]


async def test_admin_customers_are_paged_by_the_user_repository() -> None:
    service, _, _, users = _service()
    await users.add(User(id=0, email="ada@example.com", name="Ada"))

    page = await service.list_customers(PaginationParams(page=1, page_size=20))

    assert [user.email for user in page.items] == ["ada@example.com"]
    assert page.total == 1
    assert users.listed == [(20, 0)]


# ── Creating a product ───────────────────────────────────────────────


async def test_creating_a_product_offers_the_sizes_with_stock_on_the_shelf() -> None:
    service, products, _, _ = _service()

    product = await service.create_product(_command())

    assert product.id != 0
    assert product.slug == "new-jersey"
    assert product.sizes == ["M", "L"]
    assert product.stock == {"M": 4, "L": 0}
    assert product.primary_image == "/new.jpg"
    # An admin does not have to invent stock codes: the catalog names them.
    assert [variant.sku for variant in product.variants] == ["new-jersey-M", "new-jersey-L"]
    assert product.category.slug == "curated-jersey"
    assert await products.get_by_slug("new-jersey") is product


async def test_a_product_may_keep_its_own_stock_codes() -> None:
    service, _, _, _ = _service()

    product = await service.create_product(
        _command(sizes=(NewSize(size="M", quantity=2, sku="ZD-MED-01"),))
    )

    assert product.variants[0].sku == "ZD-MED-01"


async def test_creating_a_product_that_takes_a_name_already_in_the_catalog_is_refused() -> None:
    service, products, _, _ = _service()
    await products.add(_product("new-jersey"))

    with pytest.raises(ConflictError):
        await service.create_product(_command())

    # The catalog still holds the one product, not a second one sharing its name.
    assert await products.count_active() == 1


async def test_a_product_cannot_be_offered_in_the_same_size_twice() -> None:
    service, products, _, _ = _service()

    with pytest.raises(ValidationError):
        await service.create_product(
            _command(sizes=(NewSize(size="M", quantity=1), NewSize(size="m", quantity=2)))
        )

    assert await products.count_active() == 0


async def test_the_product_rules_are_checked_on_the_way_in_not_around_the_way_in() -> None:
    service, products, _, _ = _service()

    with pytest.raises(ValidationError):
        await service.create_product(_command(price=Decimal("-1.00")))

    assert await products.count_active() == 0


# ── Editing a product ────────────────────────────────────────────────


async def test_editing_a_product_changes_only_what_was_sent() -> None:
    service, products, _, _ = _service()
    product = await products.add(_product("alpha", price=Decimal("1000.00"), stock={"M": 3}))

    edited = await service.update_product(product.id, {"name": "Alpha Home", "is_bestseller": True})

    assert edited.name == "Alpha Home"
    assert edited.is_bestseller is True
    # Untouched: the price, the stock, the category and the identity.
    assert edited.price == Decimal("1000.00")
    assert edited.stock == {"M": 3}
    assert edited.slug == "alpha"


async def test_an_edit_that_breaks_a_product_rule_is_never_written() -> None:
    service, products, _, _ = _service()
    product = await products.add(_product("alpha"))

    with pytest.raises(ValidationError):
        await service.update_product(product.id, {"price": Decimal("-5.00")})

    assert products.saved == []


async def test_a_products_identity_is_not_an_editable_detail() -> None:
    service, products, _, _ = _service()
    product = await products.add(_product("alpha"))

    with pytest.raises(ValidationError):
        await service.update_product(product.id, {"slug": "renamed"})

    assert product.slug == "alpha"
    assert products.saved == []


async def test_editing_a_product_that_is_not_there_is_not_found() -> None:
    service, _, _, _ = _service()

    with pytest.raises(NotFoundError):
        await service.update_product(404, {"name": "Anything"})


async def test_hiding_a_product_is_a_flag_not_a_deletion() -> None:
    service, products, _, _ = _service()
    product = await products.add(_product("alpha"))

    edited = await service.update_product(product.id, {"is_active": False})

    assert edited.is_active is False
    # The storefront read is the one that stops showing it; the record survives.
    assert await products.get_by_id(product.id) is not None
    assert await products.count_active() == 0


# ── Restocking ───────────────────────────────────────────────────────


async def test_restocking_puts_units_back_where_they_sold_out() -> None:
    service, products, _, _ = _service()
    product = await products.add(_product("alpha", stock={"M": 0, "L": 7}))

    receipt = await service.restock(product.id, RestockCommand(size="M", quantity=12))

    assert (receipt.added, receipt.available) == (12, 12)
    assert product.stock == {"M": 12, "L": 7}
    assert products.saved == [product.id]


async def test_restocking_leaves_what_is_already_promised_alone() -> None:
    service, products, _, _ = _service()
    product = await products.add(_product("alpha", stock={"M": 2}, reserved={"M": 2}))

    receipt = await service.restock(product.id, RestockCommand(size="M", quantity=3))

    assert product.variants[0].inventory.reserved == 2
    # Three more made, two still spoken for.
    assert receipt.available == 3


async def test_restocking_is_case_insensitive_about_the_size_label() -> None:
    service, products, _, _ = _service()
    product = await products.add(_product("alpha", stock={"XL": 1}))

    receipt = await service.restock(product.id, RestockCommand(size="xl", quantity=1))

    assert receipt.size == "XL"
    assert receipt.available == 2


@pytest.mark.parametrize("quantity", [0, -5])
async def test_the_store_never_receives_zero_or_negative_units(quantity: int) -> None:
    service, products, _, _ = _service()
    product = await products.add(_product("alpha", stock={"M": 4}))

    with pytest.raises(ValidationError):
        await service.restock(product.id, RestockCommand(size="M", quantity=quantity))

    assert product.stock == {"M": 4}
    assert products.saved == []


async def test_stock_cannot_be_sent_to_a_size_the_product_is_not_offered_in() -> None:
    service, products, _, _ = _service()
    product = await products.add(_product("alpha", stock={"M": 4}))

    with pytest.raises(NotFoundError):
        await service.restock(product.id, RestockCommand(size="XXL", quantity=4))

    assert products.saved == []


async def test_stock_cannot_be_sent_to_a_product_that_does_not_exist() -> None:
    service, _, _, _ = _service()

    with pytest.raises(NotFoundError):
        await service.restock(404, RestockCommand(size="M", quantity=4))
