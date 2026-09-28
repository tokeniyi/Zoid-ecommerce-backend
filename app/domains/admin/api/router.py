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

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.domains.admin.api.schemas import (
    AdminDashboardResponse,
    AdminOrderListResponse,
    AdminProductCreateRequest,
    AdminProductResponse,
    AdminProductUpdateRequest,
    AdminStockIncreaseRequest,
    AdminStockResponse,
    AdminUserListResponse,
    serialize_dashboard,
    serialize_orders,
    serialize_product,
    serialize_users,
)
from app.domains.admin.application.service import (
    AdminService,
    NewImage,
    NewProductCommand,
    NewSize,
    RestockCommand,
)
from app.infrastructure.container import get_admin_service
from app.security.authorization import require_admin
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


@router.get("/dashboard", response_model=AdminDashboardResponse)
async def get_dashboard(
    service: Annotated[AdminService, Depends(get_admin_service)],
) -> AdminDashboardResponse:
    """One look at the store: catalog, order book and customers."""
    return serialize_dashboard(await service.dashboard())


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


@router.get("/orders", response_model=AdminOrderListResponse)
async def list_orders(
    service: Annotated[AdminService, Depends(get_admin_service)],
    params: Annotated[PaginationParams, Depends(get_pagination)],
) -> AdminOrderListResponse:
    """Every customer's orders, newest first — paid ones included, by status."""
    return serialize_orders(await service.list_orders(params))


@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    service: Annotated[AdminService, Depends(get_admin_service)],
    params: Annotated[PaginationParams, Depends(get_pagination)],
) -> AdminUserListResponse:
    """Every registered customer, earliest first."""
    return serialize_users(await service.list_customers(params))
