"""Products API schemas and domain->transport serializers.

The public shape mirrors the storefront's product fields (snake_case on the
wire). Serialisation lives at the edge so the domain entities stay free of
Pydantic/HTTP concerns.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.domains.products.domain.entities import Category, Product
from app.shared.pagination import Page


class CategoryResponse(BaseModel):
    id: int
    name: str
    slug: str


class ProductImageResponse(BaseModel):
    url: str
    view: str


class ProductSummaryResponse(BaseModel):
    id: int
    slug: str
    name: str
    category: str
    price: float
    currency: str
    image: str | None
    sizes: list[str]
    stock: dict[str, int]
    is_bestseller: bool
    is_special: bool


class ProductDetailResponse(ProductSummaryResponse):
    gallery: list[ProductImageResponse]
    tone: str
    style: str
    color: str
    fit: str
    fit_note: str
    details: str
    delivery: str


class ProductListResponse(BaseModel):
    items: list[ProductSummaryResponse]
    page: int
    page_size: int
    total: int
    total_pages: int


def serialize_category(category: Category) -> CategoryResponse:
    return CategoryResponse(
        id=category.id,
        name=category.name,
        slug=category.slug,
    )


def serialize_summary(product: Product) -> ProductSummaryResponse:
    return ProductSummaryResponse(
        id=product.id,
        slug=product.slug,
        name=product.name,
        category=product.category.name,
        price=float(product.price),
        currency=product.currency,
        image=product.primary_image,
        sizes=product.sizes,
        stock=product.stock,
        is_bestseller=product.is_bestseller,
        is_special=product.is_special,
    )


def serialize_detail(product: Product) -> ProductDetailResponse:
    return ProductDetailResponse(
        **serialize_summary(product).model_dump(),
        gallery=[
            ProductImageResponse(url=image.url, view=image.view)
            for image in product.images
        ],
        tone=product.tone,
        style=product.style,
        color=product.color,
        fit=product.fit,
        fit_note=product.fit_note,
        details=product.details,
        delivery=product.delivery,
    )


def serialize_page(page: Page[Product]) -> ProductListResponse:
    return ProductListResponse(
        items=[serialize_summary(product) for product in page.items],
        page=page.page,
        page_size=page.page_size,
        total=page.total,
        total_pages=page.total_pages,
    )
