"""Admin API request/response schemas.

Request limits mirror the columns the values are stored in: a value that is too
long for the database is a client error (422), not a failed write. Everything a
product must satisfy as a *product* stays in the product domain, so it is not
repeated here.

Responses deliberately reuse the shapes the storefront already publishes (a
product is one product, seen from either side) instead of inventing an admin-only
copy of the same record.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from app.domains.admin.application.service import DashboardOverview
from app.domains.orders.api.schemas import OrderResponse, serialize_order
from app.domains.orders.domain.entities import Order
from app.domains.products.api.schemas import ProductDetailResponse, serialize_detail
from app.domains.products.domain.entities import Product
from app.domains.users.api.schemas import UserProfileResponse
from app.domains.users.domain.entities import User
from app.shared.pagination import Page

#: What an admin may edit on an existing product. Identity (slug) and the size
#: list are not on this list, and the domain refuses them too.


class AdminProductResponse(ProductDetailResponse):
    """The storefront's product shape plus the one field only the shop acts on.

    ``is_active`` is deliberately invisible to a customer — a hidden product is
    simply not on the shelf — but an admin both sets it (the reversible
    alternative to deleting) and must be able to read back that the change took.
    """

    is_active: bool


class AdminProductImageRequest(BaseModel):
    """One gallery image as it is added."""

    url: str = Field(min_length=1, max_length=500)
    view: str = Field(default="front", max_length=20)


class AdminProductSizeRequest(BaseModel):
    """A size the product is offered in, with the units first stocked."""

    size: str = Field(min_length=1, max_length=20)
    quantity: int = Field(default=0, ge=0)
    sku: str | None = Field(default=None, max_length=80)


class AdminProductCreateRequest(BaseModel):
    """A new catalog product. ``sizes`` are the variants it is sold in."""

    slug: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=200)
    category_slug: str = Field(min_length=1, max_length=140)
    category_name: str = Field(min_length=1, max_length=120)
    price: Decimal = Field(ge=0)
    currency: str = Field(default="NGN", min_length=3, max_length=3)
    sizes: list[AdminProductSizeRequest] = Field(default_factory=list)
    images: list[AdminProductImageRequest] = Field(default_factory=list)
    tone: str = Field(default="", max_length=120)
    style: str = Field(default="", max_length=120)
    color: str = Field(default="", max_length=60)
    fit: str = Field(default="", max_length=60)
    fit_note: str = ""
    details: str = ""
    delivery: str = Field(default="", max_length=120)
    is_bestseller: bool = False
    is_special: bool = False
    is_active: bool = True


class AdminProductUpdateRequest(BaseModel):
    """Edit a product's details. A field left out keeps the value it has.

    An explicit ``null`` counts as left out: PATCH here means "change what you
    named", and clearing a description to an empty string is done by sending it
    empty.
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    price: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    tone: str | None = Field(default=None, max_length=120)
    style: str | None = Field(default=None, max_length=120)
    color: str | None = Field(default=None, max_length=60)
    fit: str | None = Field(default=None, max_length=60)
    fit_note: str | None = None
    details: str | None = None
    delivery: str | None = Field(default=None, max_length=120)
    is_bestseller: bool | None = None
    is_special: bool | None = None
    #: Hiding a product from the storefront is the reversible alternative to
    #: deleting it, which this store does not do.
    is_active: bool | None = None

    def changes(self) -> dict[str, object]:
        """Only the fields the caller actually sent, keyed as the domain names them."""
        return self.model_dump(exclude_unset=True, exclude_none=True)


class AdminStockIncreaseRequest(BaseModel):
    """Restock one size. Stock is only ever *added* through this endpoint."""

    size: str = Field(min_length=1, max_length=20)
    quantity: int = Field(ge=1)


class AdminStockResponse(BaseModel):
    """What a restock did."""

    product_id: int
    size: str
    added: int
    available: int


class AdminCatalogStatsResponse(BaseModel):
    products: int
    units_available: int
    inventory_value: float
    out_of_stock: int
    low_stock: int
    bestsellers: int
    specials: int


class AdminOrderStatsResponse(BaseModel):
    total: int
    paid: int
    awaiting_payment: int


class AdminCustomerStatsResponse(BaseModel):
    total: int


class AdminDashboardResponse(BaseModel):
    """One look at the whole store."""

    catalog: AdminCatalogStatsResponse
    orders: AdminOrderStatsResponse
    customers: AdminCustomerStatsResponse
    needs_restocking: int


class AdminOrderListResponse(BaseModel):
    items: list[OrderResponse]
    page: int
    page_size: int
    total: int
    total_pages: int


class AdminUserListResponse(BaseModel):
    items: list[UserProfileResponse]
    page: int
    page_size: int
    total: int
    total_pages: int


def serialize_dashboard(overview: DashboardOverview) -> AdminDashboardResponse:
    catalog = overview.catalog
    orders = overview.orders
    return AdminDashboardResponse(
        catalog=AdminCatalogStatsResponse(
            products=catalog.products,
            units_available=catalog.units_available,
            inventory_value=float(catalog.inventory_value),
            out_of_stock=catalog.out_of_stock,
            low_stock=catalog.low_stock,
            bestsellers=catalog.bestsellers,
            specials=catalog.specials,
        ),
        orders=AdminOrderStatsResponse(
            total=orders.total,
            paid=orders.paid,
            awaiting_payment=orders.awaiting_payment,
        ),
        customers=AdminCustomerStatsResponse(total=overview.customers.total),
        needs_restocking=overview.needs_restocking,
    )


def serialize_product(product: Product) -> AdminProductResponse:
    return AdminProductResponse(
        **serialize_detail(product).model_dump(),
        is_active=product.is_active,
    )


def serialize_orders(page: Page[Order]) -> AdminOrderListResponse:
    """The full order, lines and delivery details included: an admin has to act
    on the order, not just see that it exists."""
    return AdminOrderListResponse(
        items=[serialize_order(order) for order in page.items],
        page=page.page,
        page_size=page.page_size,
        total=page.total,
        total_pages=page.total_pages,
    )


def serialize_users(page: Page[User]) -> AdminUserListResponse:
    return AdminUserListResponse(
        items=[UserProfileResponse.model_validate(user) for user in page.items],
        page=page.page,
        page_size=page.page_size,
        total=page.total,
        total_pages=page.total_pages,
    )
