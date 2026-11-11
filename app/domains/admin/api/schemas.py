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

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.domains.admin.application.analytics import SalesReport
from app.domains.admin.application.service import DashboardOverview
from app.domains.orders.api.schemas import OrderResponse, serialize_order
from app.domains.orders.domain.entities import Order
from app.domains.orders.domain.enums import FulfillmentStatus
from app.domains.products.api.schemas import ProductDetailResponse, serialize_detail
from app.domains.products.domain.entities import Product
from app.domains.users.api.schemas import UserProfileResponse
from app.domains.users.domain.entities import User
from app.shared.money import serialize_money
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
    #: Price before a markdown; the storefront's discount is computed from it.
    original_price: Decimal | None = Field(default=None, ge=0)
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
    is_new_arrival: bool = False
    is_active: bool = True


class AdminProductUpdateRequest(BaseModel):
    """Edit a product's details. A field left out keeps the value it has.

    An explicit ``null`` counts as left out: PATCH here means "change what you
    named", and clearing a description to an empty string is done by sending it
    empty. The one exception is ``original_price``, where ``null`` ends a sale.
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    price: Decimal | None = Field(default=None, ge=0)
    #: Unlike the other fields an explicit ``null`` here *clears* the markdown
    #: (ends the sale); leaving the field out keeps it.
    original_price: Decimal | None = Field(default=None, ge=0)
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
    is_new_arrival: bool | None = None
    #: Hiding a product from the storefront is the reversible alternative to
    #: deleting it, which this store does not do.
    is_active: bool | None = None

    def changes(self) -> dict[str, object]:
        """Only the fields the caller actually sent, keyed as the domain names them."""
        changes = self.model_dump(exclude_unset=True, exclude_none=True)
        if "original_price" in self.model_fields_set and self.original_price is None:
            changes["original_price"] = None  # an explicit null ends the sale
        return changes


class AdminStockIncreaseRequest(BaseModel):
    """Restock one size. Stock is only ever *added* through this endpoint."""

    size: str = Field(min_length=1, max_length=20)
    quantity: int = Field(ge=1)


class AdminFulfillmentRequest(BaseModel):
    """Progress on an order. Send either field, or both."""

    status: FulfillmentStatus | None = None
    #: Confirm (or correct) the GUO terminal of a pickup order.
    terminal: str | None = Field(default=None, min_length=1, max_length=200)


class AdminImageUploadResponse(BaseModel):
    """Where an uploaded image now lives. Use ``url`` in a product's ``images``."""

    url: str
    key: str
    content_type: str
    size: int


class AdminStockAdjustRequest(BaseModel):
    """Correct one size's stock: by an amount (``delta``, may be negative) or to an
    amount (``set_to``, a stock-take). Send exactly one."""

    size: str = Field(min_length=1, max_length=20)
    delta: int | None = None
    set_to: int | None = Field(default=None, ge=0)


class AdminStockAdjustResponse(BaseModel):
    product_id: int
    size: str
    #: How much the count moved (negative when stock was removed).
    change: int
    quantity: int
    #: Units already promised to customers' orders; stock can never go below this.
    reserved: int
    available: int


class AdminProductListResponse(BaseModel):
    items: list[AdminProductResponse]
    page: int
    page_size: int
    total: int
    total_pages: int


class AdminStockResponse(BaseModel):
    """What a restock did."""

    product_id: int
    size: str
    added: int
    available: int


class AdminCatalogStatsResponse(BaseModel):
    products: int
    units_available: int
    inventory_value: str
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
            inventory_value=serialize_money(catalog.inventory_value),
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


def serialize_products(page: Page[Product]) -> AdminProductListResponse:
    return AdminProductListResponse(
        items=[serialize_product(product) for product in page.items],
        page=page.page,
        page_size=page.page_size,
        total=page.total,
        total_pages=page.total_pages,
    )


# ── analytics ───────────────────────────────────────────────────────────


class AdminPeriodResponse(BaseModel):
    date_from: date
    date_to: date
    days: int


class AdminSalesResponse(BaseModel):
    #: Money collected: the total of *paid* orders. Unpaid orders are not revenue.
    revenue: str
    orders: int
    paid_orders: int
    awaiting_payment_orders: int
    cancelled_orders: int
    units_sold: int
    average_order_value: str
    previous_revenue: str
    #: Whole-number change against the previous period; null when that had none.
    change_percent: int | None


class AdminAccountingResponse(BaseModel):
    #: Goods only, before personalisation, delivery and refunds.
    gross_sales: str
    customization_charges: str
    delivery_charges: str
    total_collected: str
    #: Orders placed but not yet paid.
    outstanding: str


class AdminOperationsResponse(BaseModel):
    processing: int
    in_transit: int
    delivered: int
    hand_delivery_orders: int
    pickup_orders: int
    pending_terminal_confirmations: int


class AdminTopProductResponse(BaseModel):
    product_slug: str
    product_name: str
    image: str
    units_sold: int
    revenue: str


class AdminDailyPointResponse(BaseModel):
    date: date
    revenue: str
    orders: int
    paid_orders: int
    units_sold: int


class AdminAnalyticsResponse(BaseModel):
    period: AdminPeriodResponse
    sales: AdminSalesResponse
    accounting: AdminAccountingResponse
    operations: AdminOperationsResponse
    top_products: list[AdminTopProductResponse]
    daily: list[AdminDailyPointResponse]


def serialize_analytics(report: SalesReport) -> AdminAnalyticsResponse:
    sales, accounting, operations = report.sales, report.accounting, report.operations
    return AdminAnalyticsResponse(
        period=AdminPeriodResponse(
            date_from=report.period.first_day,
            date_to=report.period.last_day,
            days=report.period.days,
        ),
        sales=AdminSalesResponse(
            revenue=serialize_money(sales.revenue),
            orders=sales.orders,
            paid_orders=sales.paid_orders,
            awaiting_payment_orders=sales.awaiting_payment_orders,
            cancelled_orders=sales.cancelled_orders,
            units_sold=sales.units_sold,
            average_order_value=serialize_money(sales.average_order_value),
            previous_revenue=serialize_money(sales.previous_revenue),
            change_percent=sales.change_percent,
        ),
        accounting=AdminAccountingResponse(
            gross_sales=serialize_money(accounting.gross_sales),
            customization_charges=serialize_money(accounting.customization_charges),
            delivery_charges=serialize_money(accounting.delivery_charges),
            total_collected=serialize_money(accounting.total_collected),
            outstanding=serialize_money(accounting.outstanding),
        ),
        operations=AdminOperationsResponse(
            processing=operations.processing,
            in_transit=operations.in_transit,
            delivered=operations.delivered,
            hand_delivery_orders=operations.hand_delivery_orders,
            pickup_orders=operations.pickup_orders,
            pending_terminal_confirmations=operations.pending_terminal_confirmations,
        ),
        top_products=[
            AdminTopProductResponse(
                product_slug=p.product_slug,
                product_name=p.product_name,
                image=p.image,
                units_sold=p.units_sold,
                revenue=serialize_money(p.revenue),
            )
            for p in report.top_products
        ],
        daily=[
            AdminDailyPointResponse(
                date=point.day,
                revenue=serialize_money(point.revenue),
                orders=point.orders,
                paid_orders=point.paid_orders,
                units_sold=point.units_sold,
            )
            for point in report.daily
        ],
    )
