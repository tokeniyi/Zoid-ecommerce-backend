"""Products HTTP routes — public catalog (no authentication).

Thin transport layer: delegates to `ProductService` and serialises domain
entities at the edge. No database access happens here.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.domains.products.api.schemas import (
    CategoryResponse,
    ProductDetailResponse,
    ProductListResponse,
    serialize_category,
    serialize_detail,
    serialize_page,
)
from app.domains.products.application.service import ProductService
from app.infrastructure.container import get_product_service
from app.shared.pagination import PaginationParams

router = APIRouter(tags=["products"])


def get_pagination(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginationParams:
    return PaginationParams(page=page, page_size=page_size)


@router.get("/products", response_model=ProductListResponse)
async def list_products(
    service: Annotated[ProductService, Depends(get_product_service)],
    params: Annotated[PaginationParams, Depends(get_pagination)],
) -> ProductListResponse:
    """List active products."""
    return serialize_page(await service.list_products(params))


@router.get("/products/{identifier}", response_model=ProductDetailResponse)
async def get_product(
    identifier: str,
    service: Annotated[ProductService, Depends(get_product_service)],
) -> ProductDetailResponse:
    """Get a single product by id or slug."""
    return serialize_detail(await service.get_product(identifier))


@router.get("/categories", response_model=list[CategoryResponse])
async def list_categories(
    service: Annotated[ProductService, Depends(get_product_service)],
) -> list[CategoryResponse]:
    """List catalog categories."""
    return [serialize_category(c) for c in await service.list_categories()]
