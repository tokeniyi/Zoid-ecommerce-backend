"""Admin HTTP routes — the shop's own side of the API.

The whole surface is guarded once, on the router: authentication and the
admin-role check run before any endpoint body, any repository call and any
request-model validation. Hiding ``/admin`` in the frontend is a convenience,
never the protection ("Never rely only on hiding the frontend page"), so a
customer who types these URLs into a browser gets 403 and an anonymous caller
gets 401 — the same answers the real UI would have had to enforce.

Declaring the guard on the router rather than per endpoint is what makes it
load-bearing: an endpoint added here later cannot be left open by forgetting to
decorate it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.config import get_settings
from app.domains.admin.api.schemas import (
    AdminAnalyticsResponse,
    AdminDashboardResponse,
    AdminFulfillmentRequest,
    AdminImageUploadResponse,
    AdminOrderListResponse,
    AdminProductCreateRequest,
    AdminProductListResponse,
    AdminProductResponse,
    AdminProductUpdateRequest,
    AdminStockAdjustRequest,
    AdminStockAdjustResponse,
    AdminStockIncreaseRequest,
    AdminStockResponse,
    AdminUserListResponse,
    serialize_analytics,
    serialize_dashboard,
    serialize_orders,
    serialize_product,
    serialize_products,
    serialize_users,
)
from app.domains.admin.application.analytics import Period
from app.domains.admin.application.images import ProductImageService
from app.domains.admin.application.service import (
    AdminService,
    FulfillmentUpdate,
    NewImage,
    NewProductCommand,
    NewSize,
    RestockCommand,
    StockAdjustment,
)
from app.domains.orders.api.schemas import OrderResponse, serialize_order
from app.domains.orders.domain.criteria import OrderCriteria
from app.domains.orders.domain.enums import FulfillmentStatus, OrderPaymentStatus
from app.domains.products.api.router import get_criteria
from app.domains.products.domain.entities import StockStatus
from app.domains.products.domain.search import ProductCriteria
from app.infrastructure.container import get_admin_service, get_product_image_service
from app.security.authorization import require_admin
from app.shared.exceptions import ValidationError
from app.shared.pagination import PaginationParams

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


def get_pagination(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginationParams:
    """Offset pagination for the admin ledgers (declared here, per domain router)."""
    return PaginationParams(page=page, page_size=page_size)


def store_timezone() -> timezone:
    """The store's own clock: which calendar day an order belongs to."""
    return timezone(timedelta(minutes=get_settings().store_utc_offset_minutes))


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=store_timezone()).astimezone(UTC)


async def _read_capped(request: Request, limit: int) -> bytes:
    """The request body, refusing as soon as it passes ``limit`` bytes.

    Read in chunks so an oversized upload is cut off instead of being held in
    memory first and measured afterwards.
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise ValidationError(f"The image is too large; the limit is {limit} bytes.")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise ValidationError(f"The image is too large; the limit is {limit} bytes.")
    return bytes(body)


@router.get("/dashboard", response_model=AdminDashboardResponse)
async def get_dashboard(
    service: Annotated[AdminService, Depends(get_admin_service)],
) -> AdminDashboardResponse:
    """One look at the store: catalog, order book and customers."""
    return serialize_dashboard(await service.dashboard())


@router.get("/products", response_model=AdminProductListResponse)
async def list_products(
    service: Annotated[AdminService, Depends(get_admin_service)],
    params: Annotated[PaginationParams, Depends(get_pagination)],
    criteria: Annotated[ProductCriteria, Depends(get_criteria)],
    active: Annotated[
        bool | None, Query(description="true: on the shelf; false: hidden; omit: both.")
    ] = None,
    stock: Annotated[StockStatus | None, Query(description="How it is stocked.")] = None,
) -> AdminProductListResponse:
    """The whole catalog, hidden products included.

    Takes the storefront's search, filters and sorting (so the screen finds things
    the way a shopper would) plus ``active`` and ``stock``. Hiding a product
    (``PATCH`` with ``is_active: false``) archives it; setting it back unarchives.
    """
    return serialize_products(
        await service.list_products(params, criteria, active=active, stock=stock)
    )


@router.post(
    "/products/images",
    response_model=AdminImageUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_product_image(
    request: Request,
    service: Annotated[ProductImageService, Depends(get_product_image_service)],
) -> AdminImageUploadResponse:
    """Store a product image and get back its public URL.

    Send the image's raw bytes as the request body (``fetch(url, {method: "POST",
    body: file})``) - JPEG, PNG, GIF or WebP, up to ``MAX_UPLOAD_BYTES``. The file is
    identified by its contents, not by the type or name the browser claims, and is
    stored under a name the server generates. Put the returned ``url`` in the
    ``images`` of ``POST /admin/products``; an already-hosted address can still be
    given there directly.
    """
    content = await _read_capped(request, get_settings().max_upload_bytes)
    uploaded = await service.upload(content)
    return AdminImageUploadResponse(
        url=uploaded.url,
        key=uploaded.key,
        content_type=uploaded.content_type,
        size=uploaded.size,
    )


@router.post(
    "/products",
    response_model=AdminProductResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_product(
    body: AdminProductCreateRequest,
    service: Annotated[AdminService, Depends(get_admin_service)],
) -> AdminProductResponse:
    """Add a product to the catalog."""
    product = await service.create_product(
        NewProductCommand(
            slug=body.slug,
            name=body.name,
            category_slug=body.category_slug,
            category_name=body.category_name,
            price=body.price,
            original_price=body.original_price,
            currency=body.currency,
            sizes=tuple(
                NewSize(size=size.size, quantity=size.quantity, sku=size.sku)
                for size in body.sizes
            ),
            images=tuple(
                NewImage(url=image.url, view=image.view) for image in body.images
            ),
            tone=body.tone,
            style=body.style,
            color=body.color,
            fit=body.fit,
            fit_note=body.fit_note,
            details=body.details,
            delivery=body.delivery,
            is_bestseller=body.is_bestseller,
            is_special=body.is_special,
            is_new_arrival=body.is_new_arrival,
            is_active=body.is_active,
        )
    )
    return serialize_product(product)


@router.patch("/products/{product_id}", response_model=AdminProductResponse)
async def update_product(
    product_id: int,
    body: AdminProductUpdateRequest,
    service: Annotated[AdminService, Depends(get_admin_service)],
) -> AdminProductResponse:
    """Edit a product's details; fields left out are unchanged."""
    product = await service.update_product(product_id, body.changes())
    return serialize_product(product)


@router.post("/products/{product_id}/stock", response_model=AdminStockResponse)
async def increase_stock(
    product_id: int,
    body: AdminStockIncreaseRequest,
    service: Annotated[AdminService, Depends(get_admin_service)],
) -> AdminStockResponse:
    """Put more units of one size on the shelf."""
    receipt = await service.restock(
        product_id,
        RestockCommand(size=body.size, quantity=body.quantity),
    )
    return AdminStockResponse(
        product_id=receipt.product_id,
        size=receipt.size,
        added=receipt.added,
        available=receipt.available,
    )


@router.patch("/products/{product_id}/stock", response_model=AdminStockAdjustResponse)
async def adjust_stock(
    product_id: int,
    body: AdminStockAdjustRequest,
    service: Annotated[AdminService, Depends(get_admin_service)],
) -> AdminStockAdjustResponse:
    """Correct one size's stock, up or down: ``delta`` (-3 removes three) or
    ``set_to`` (a stock-take). Stock can never go below what customers' orders
    have already reserved (422)."""
    receipt = await service.adjust_stock(
        product_id, StockAdjustment(size=body.size, delta=body.delta, set_to=body.set_to)
    )
    return AdminStockAdjustResponse(
        product_id=receipt.product_id,
        size=receipt.size,
        change=receipt.change,
        quantity=receipt.quantity,
        reserved=receipt.reserved,
        available=receipt.available,
    )


@router.get("/orders", response_model=AdminOrderListResponse)
async def list_orders(
    service: Annotated[AdminService, Depends(get_admin_service)],
    params: Annotated[PaginationParams, Depends(get_pagination)],
    payment_status: OrderPaymentStatus | None = None,
    fulfillment_status: FulfillmentStatus | None = None,
    delivery_option: Annotated[
        str | None, Query(pattern="^(standard|express|pickup)$")
    ] = None,
    q: Annotated[
        str,
        Query(max_length=100, description="Order reference, or customer name, email or phone."),
    ] = "",
    date_from: Annotated[date | None, Query(description="Placed on or after (store time).")] = None,
    date_to: Annotated[date | None, Query(description="Placed on or before (store time).")] = None,
) -> AdminOrderListResponse:
    """Every customer's orders, newest first, optionally narrowed. ``total`` counts
    the orders that matched."""
    criteria = OrderCriteria(
        payment_status=payment_status,
        fulfillment_status=fulfillment_status,
        delivery_option=delivery_option,
        query=q,
        created_from=_day_start(date_from) if date_from else None,
        created_before=_day_start(date_to + timedelta(days=1)) if date_to else None,
    )
    return serialize_orders(await service.list_orders(params, criteria))


@router.get("/analytics", response_model=AdminAnalyticsResponse)
async def get_analytics(
    service: Annotated[AdminService, Depends(get_admin_service)],
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> AdminAnalyticsResponse:
    """Revenue, accounting, operations, best sellers and a day-by-day trend.

    Defaults to the current week (Monday to Sunday, store time). Revenue is money
    actually collected (paid orders); unpaid orders show as outstanding. Every
    figure is compared with the period of equal length just before.
    """
    tz = store_timezone()
    today = datetime.now(tz).date()
    if date_from is None and date_to is None:
        period = Period.week_of(today)
    else:
        start = date_from or (date_to - timedelta(days=6))  # type: ignore[operator]
        period = Period(first_day=start, last_day=date_to or start + timedelta(days=6))
    return serialize_analytics(await service.analytics(period, tz))


@router.patch("/orders/{order_id}/fulfillment", response_model=OrderResponse)
async def update_fulfillment(
    order_id: int,
    body: AdminFulfillmentRequest,
    service: Annotated[AdminService, Depends(get_admin_service)],
) -> OrderResponse:
    """Move a paid order along (processing, in transit, delivered) and/or confirm
    the terminal of a pickup order. An unpaid order cannot be fulfilled (409)."""
    order = await service.update_fulfillment(
        order_id, FulfillmentUpdate(status=body.status, terminal=body.terminal)
    )
    return serialize_order(order)


@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    service: Annotated[AdminService, Depends(get_admin_service)],
    params: Annotated[PaginationParams, Depends(get_pagination)],
) -> AdminUserListResponse:
    """Every registered customer, earliest first."""
    return serialize_users(await service.list_customers(params))
