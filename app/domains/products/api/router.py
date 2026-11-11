"""Products HTTP routes — public catalog (no authentication).

Thin transport layer: delegates to `ProductService` and serialises domain
entities at the edge. No database access happens here.
"""

from __future__ import annotations

from decimal import Decimal
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
from app.domains.products.domain.search import ProductCriteria, ProductSort
from app.infrastructure.container import get_product_service
from app.shared.pagination import PaginationParams

router = APIRouter(tags=["products"])


def get_pagination(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginationParams:
    return PaginationParams(page=page, page_size=page_size)


def get_criteria(
    q: Annotated[
        str, Query(max_length=100, description="Forgiving search: typos are tolerated.")
    ] = "",
    category: Annotated[str | None, Query(description="Category slug.")] = None,
    style: Annotated[str | None, Query(max_length=120)] = None,
    color: Annotated[str | None, Query(max_length=60)] = None,
    size: Annotated[str | None, Query(max_length=20)] = None,
    min_price: Annotated[Decimal | None, Query(ge=0)] = None,
    max_price: Annotated[Decimal | None, Query(ge=0)] = None,
    bestseller: bool | None = None,
    special: bool | None = None,
    new_arrival: bool | None = None,
    on_sale: bool | None = None,
    sort: ProductSort | None = None,
) -> ProductCriteria:
    return ProductCriteria(
        query=q,
        category=category,
        style=style,
        color=color,
        size=size,
        min_price=min_price,
        max_price=max_price,
        bestseller=bestseller,
        special=special,
        new_arrival=new_arrival,
        on_sale=on_sale,
        sort=sort,
    )


@router.get("/products", response_model=ProductListResponse)
async def list_products(
    service: Annotated[ProductService, Depends(get_product_service)],
    params: Annotated[PaginationParams, Depends(get_pagination)],
    criteria: Annotated[ProductCriteria, Depends(get_criteria)],
) -> ProductListResponse:
    """List active products, optionally searched, filtered and sorted.

    Without any query parameter this is the whole catalog, oldest first.
    """
    return serialize_page(await service.list_products(params, criteria))


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
