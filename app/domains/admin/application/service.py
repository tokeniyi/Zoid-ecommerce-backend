"""Admin application service — the shop's own use-cases.

Everything here is the same authoritative data the customer-facing services use,
read or written from behind the counter: products go through the product
repository, orders through the order repository, customers through the user
repository. No session, no ORM model and no SQL appears in this module, so an
administrator is a *caller* of the domain rather than someone above it.

Inventory rules stay where they belong. Restocking asks the product entity to
``receive`` units — so "stock only goes up by a real amount" is enforced once, in
the domain, for whoever restocks, not only for the admin screen.

What the dashboard reports is Not Specified in Architecture beyond "the dashboard
is a consumer of the same authoritative backend data". The numbers here are the
ones the shop has to act on through this same surface: what the catalog is worth
in units, which products need restocking, how much order book is settled and how
many customers exist. Nothing here is a second source of truth.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from app.domains.admin.domain.repositories import (
    AbstractOrderRepository,
    AbstractProductRepository,
    AbstractUserRepository,
)
from app.domains.orders.domain.entities import Order
from app.domains.orders.domain.enums import OrderStatus
from app.domains.products.domain.entities import (
    Category,
    Inventory,
    Product,
    ProductImage,
    ProductVariant,
    StockStatus,
)
from app.domains.users.domain.entities import User
from app.shared.exceptions import ConflictError, NotFoundError, ValidationError
from app.shared.pagination import Page, PaginationParams

#: The largest page the pagination contract allows; the dashboard reads the
#: catalog through the same paged contract the storefront uses.
_PAGE_SIZE = 100


@dataclass(frozen=True)
class NewImage:
    """One gallery image as an admin adds it."""

    url: str
    view: str = "front"


@dataclass(frozen=True)
class NewSize:
    """A size a product is offered in, with the units first put on the shelf.

    ``sku`` is optional: an admin does not have to invent stock codes, so the
    service derives one from the product when it is missing.
    """

    size: str
    quantity: int = 0
    sku: str | None = None


@dataclass(frozen=True)
class NewProductCommand:
    """What an admin says when adding a product to the catalog."""

    slug: str
    name: str
    category_slug: str
    category_name: str
    price: Decimal
    currency: str = "NGN"
    sizes: tuple[NewSize, ...] = ()
    images: tuple[NewImage, ...] = ()
    tone: str = ""
    style: str = ""
    color: str = ""
    fit: str = ""
    fit_note: str = ""
    details: str = ""
    delivery: str = ""
    is_bestseller: bool = False
    is_special: bool = False
    is_active: bool = True


@dataclass(frozen=True)
class RestockCommand:
    """Put ``quantity`` more of ``size`` on the shelf."""

    size: str
    quantity: int


@dataclass(frozen=True)
class RestockReceipt:
    """What a restock did, reported back so the caller need not re-read it."""

    product_id: int
    size: str
    added: int
    available: int


@dataclass(frozen=True)
class CatalogStats:
    """The catalog as stock: how much is on the shelves and where it is thin."""

    products: int
    units_available: int
    inventory_value: Decimal
    out_of_stock: int
    low_stock: int
    bestsellers: int
    specials: int


@dataclass(frozen=True)
class OrderStats:
    """The order book: how much of it is settled."""

    total: int
    paid: int
    awaiting_payment: int


@dataclass(frozen=True)
class CustomerStats:
    """How many people the store has."""

    total: int


@dataclass(frozen=True)
class DashboardOverview:
    """One look at the whole store."""

    catalog: CatalogStats
    orders: OrderStats
    customers: CustomerStats

    @property
    def needs_restocking(self) -> int:
        """How many products the shop has to put stock back into.

        The action list behind ``POST /admin/products/{id}/stock``: sold out is
        the urgent half of running low, so the two are counted once here rather
        than every reader adding them up and disagreeing.
        """
        return self.catalog.out_of_stock + self.catalog.low_stock


class AdminService:
    def __init__(
        self,
        *,
        products: AbstractProductRepository,
        orders: AbstractOrderRepository,
        users: AbstractUserRepository,
    ) -> None:
        self._products = products
        self._orders = orders
        self._users = users

    # ── Reads ────────────────────────────────────────────────────────

    async def dashboard(self) -> DashboardOverview:
        """Summarise the store from the data the store already keeps."""
        catalog = await self._catalog_stats()
        orders = OrderStats(
            total=await self._orders.count_all(),
            paid=await self._orders.count_all(status=OrderStatus.PAID),
            awaiting_payment=await self._orders.count_all(
                status=OrderStatus.PENDING_PAYMENT
            ),
        )
        customers = CustomerStats(total=await self._users.count_all())
        return DashboardOverview(catalog=catalog, orders=orders, customers=customers)

    async def list_orders(self, params: PaginationParams) -> Page[Order]:
        """Every customer's orders, newest first — the shop's order ledger."""
        items = await self._orders.list_all(limit=params.limit, offset=params.offset)
        return Page(
            items=items,
            page=params.page,
            page_size=params.page_size,
            total=await self._orders.count_all(),
        )

    async def list_customers(self, params: PaginationParams) -> Page[User]:
        """Every registered customer, earliest first."""
        items = await self._users.list_all(limit=params.limit, offset=params.offset)
        return Page(
            items=items,
            page=params.page,
            page_size=params.page_size,
            total=await self._users.count_all(),
        )

    async def _catalog_stats(self) -> CatalogStats:
        products = await self._active_catalog()
        units = sum(product.units_available for product in products)
        value = sum(
            (product.units_available * product.price for product in products),
            Decimal("0"),
        )
        statuses = [product.stock_status for product in products]
        return CatalogStats(
            products=len(products),
            units_available=units,
            inventory_value=value,
            out_of_stock=statuses.count(StockStatus.OUT_OF_STOCK),
            low_stock=statuses.count(StockStatus.LOW_STOCK),
            bestsellers=sum(1 for product in products if product.is_bestseller),
            specials=sum(1 for product in products if product.is_special),
        )

    async def _active_catalog(self) -> list[Product]:
        """Every active product, paged through the catalog's own contract.

        The product repository offers pages rather than a whole-table read, and
        the dashboard counts the whole store, so it walks the pages.
        """
        collected: list[Product] = []
        offset = 0
        while True:
            page = await self._products.list_active(limit=_PAGE_SIZE, offset=offset)
            collected.extend(page)
            if len(page) < _PAGE_SIZE:
                return collected
            offset += _PAGE_SIZE

    # ── Writes ───────────────────────────────────────────────────────

    async def create_product(self, command: NewProductCommand) -> Product:
        """Add a product to the catalog.

        A slug is how the storefront links to a product, so two products cannot
        share one; saying so here turns a rejected write into a conflict the
        caller can act on. The unique index still has the last word.
        """
        if await self._products.get_by_slug(command.slug) is not None:
            raise ConflictError(f"A product named '{command.slug}' is already in the catalog.")
        sizes = [size.size.strip() for size in command.sizes]
        if len({size.casefold() for size in sizes}) != len(sizes):
            raise ValidationError("A product cannot be offered in the same size twice.")

        product = Product(
            id=0,
            slug=command.slug,
            name=command.name,
            category=Category(id=0, name=command.category_name, slug=command.category_slug),
            price=command.price,
            currency=command.currency,
            images=[ProductImage(url=image.url, view=image.view) for image in command.images],
            variants=[
                ProductVariant(
                    id=0,
                    sku=size.sku or f"{command.slug}-{size.size}",
                    size=size.size,
                    inventory=Inventory(quantity=size.quantity),
                )
                for size in command.sizes
            ],
            tone=command.tone,
            style=command.style,
            color=command.color,
            fit=command.fit,
            fit_note=command.fit_note,
            details=command.details,
            delivery=command.delivery,
            is_bestseller=command.is_bestseller,
            is_special=command.is_special,
            is_active=command.is_active,
        )
        product.validate()
        return await self._products.add(product)

    async def update_product(self, product_id: int, changes: Mapping[str, object]) -> Product:
        """Edit a product's own details; a field that was not sent is left alone.

        The entity decides what may change and re-checks the result, so an edit
        cannot leave a product the catalog would not have created — and the
        product's identity (its slug) and its size list are not editable here.
        """
        product = await self._load_product(product_id)
        product.apply_details(dict(changes))
        return await self._save(product)

    async def restock(self, product_id: int, command: RestockCommand) -> RestockReceipt:
        """Add units of one size back to the shelf."""
        product = await self._load_product(product_id)
        variant = product.find_variant(command.size)
        if variant is None:
            raise NotFoundError(
                f"'{product.name}' is not offered in size '{command.size}'."
            )
        variant.inventory.receive(command.quantity)
        await self._save(product)
        return RestockReceipt(
            product_id=product.id,
            size=variant.size,
            added=command.quantity,
            available=variant.inventory.available,
        )

    async def _load_product(self, product_id: int) -> Product:
        """The product an admin asked about, sold out or not.

        ``get_by_id`` is the catalog's own read; a hidden product is still here
        because editing it back to life is exactly what the shop may need to do.
        """
        product = await self._products.get_by_id(product_id)
        if product is None:
            raise NotFoundError("Product not found.")
        return product

    async def _save(self, product: Product) -> Product:
        saved = await self._products.save(product)
        if saved is None:  # pragma: no cover - loaded in this same transaction
            raise NotFoundError("Product not found.")
        return saved
