"""SQLAlchemy product repository — implements the products-domain contract.

Relationships (category, images, variants, inventory) are eager-loaded by the
mappers so reading a product never triggers lazy IO on the async session.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.products.domain.entities import (
    Category,
    Inventory,
    Product,
    ProductImage,
    ProductVariant,
)
from app.domains.products.domain.repositories import AbstractProductRepository
from app.infrastructure.persistence.sqlalchemy.models.category import CategoryRow
from app.infrastructure.persistence.sqlalchemy.models.inventory import InventoryRow
from app.infrastructure.persistence.sqlalchemy.models.product import ProductRow
from app.infrastructure.persistence.sqlalchemy.models.product_image import (
    ProductImageRow,
)
from app.infrastructure.persistence.sqlalchemy.models.product_variant import (
    ProductVariantRow,
)


class SqlProductRepository(AbstractProductRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, product: Product) -> Product:
        category = await self._get_or_create_category(product.category)
        row = ProductRow(
            slug=product.slug,
            name=product.name,
            category=category,
            price=product.price,
            currency=product.currency,
            tone=product.tone,
            style=product.style,
            color=product.color,
            fit=product.fit,
            fit_note=product.fit_note,
            details=product.details,
            delivery=product.delivery,
            is_bestseller=product.is_bestseller,
            is_special=product.is_special,
            is_active=product.is_active,
        )
        for position, image in enumerate(product.images):
            row.images.append(
                ProductImageRow(url=image.url, view=image.view, position=position)
            )
        for variant in product.variants:
            row.variants.append(
                ProductVariantRow(
                    sku=variant.sku,
                    size=variant.size,
                    inventory=InventoryRow(
                        quantity=variant.inventory.quantity,
                        reserved=variant.inventory.reserved,
                    ),
                )
            )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return self._to_domain(row)

    async def get_by_id(self, product_id: int) -> Product | None:
        row = await self._session.get(ProductRow, product_id)
        return self._to_domain(row) if row is not None else None

    async def get_by_slug(self, slug: str) -> Product | None:
        row = (
            await self._session.execute(select(ProductRow).where(ProductRow.slug == slug))
        ).scalar_one_or_none()
        return self._to_domain(row) if row is not None else None

    async def list_active(self, *, limit: int, offset: int) -> list[Product]:
        stmt = (
            select(ProductRow)
            .where(ProductRow.is_active.is_(True))
            .order_by(ProductRow.id)
            .limit(limit)
            .offset(offset)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [self._to_domain(row) for row in rows]

    async def count_active(self) -> int:
        stmt = select(func.count()).select_from(ProductRow).where(ProductRow.is_active.is_(True))
        return (await self._session.execute(stmt)).scalar_one()

    async def save(self, product: Product) -> Product | None:
        row = await self._session.get(ProductRow, product.id)
        if row is None:
            return None
        row.name = product.name
        row.price = product.price
        row.currency = product.currency
        row.tone = product.tone
        row.style = product.style
        row.color = product.color
        row.fit = product.fit
        row.fit_note = product.fit_note
        row.details = product.details
        row.delivery = product.delivery
        row.is_bestseller = product.is_bestseller
        row.is_special = product.is_special
        row.is_active = product.is_active
        # Only the counts an admin restock moved are written back: reservations
        # are the checkout path's, and the variant list itself is immutable here.
        quantities = {variant.id: variant.inventory.quantity for variant in product.variants}
        for variant in row.variants:
            quantity = quantities.get(variant.id)
            if quantity is not None and variant.inventory is not None:
                variant.inventory.quantity = quantity
        await self._session.flush()
        await self._session.refresh(row)
        return self._to_domain(row)

    async def reserve_stock(self, variant_id: int, quantity: int) -> bool:
        variant = await self._session.get(ProductVariantRow, variant_id)
        if variant is None or variant.inventory is None:
            return False
        inventory = variant.inventory
        if inventory.quantity - inventory.reserved < quantity:
            return False
        inventory.reserved += quantity
        await self._session.flush()
        return True

    async def _get_or_create_category(self, category: Category) -> CategoryRow:
        row = (
            await self._session.execute(
                select(CategoryRow).where(CategoryRow.slug == category.slug)
            )
        ).scalar_one_or_none()
        if row is None:
            row = CategoryRow(name=category.name, slug=category.slug)
            self._session.add(row)
            await self._session.flush()
        return row

    @staticmethod
    def _to_domain(row: ProductRow) -> Product:
        return Product(
            id=row.id,
            slug=row.slug,
            name=row.name,
            category=Category(
                id=row.category.id, name=row.category.name, slug=row.category.slug
            ),
            price=row.price,
            currency=row.currency,
            images=[ProductImage(url=image.url, view=image.view) for image in row.images],
            variants=[
                ProductVariant(
                    id=variant.id,
                    sku=variant.sku,
                    size=variant.size,
                    inventory=Inventory(
                        quantity=variant.inventory.quantity,
                        reserved=variant.inventory.reserved,
                    ),
                )
                for variant in row.variants
            ],
            tone=row.tone,
            style=row.style,
            color=row.color,
            fit=row.fit,
            fit_note=row.fit_note,
            details=row.details,
            delivery=row.delivery,
            is_bestseller=row.is_bestseller,
            is_special=row.is_special,
            is_active=row.is_active,
            created_at=row.created_at,
        )
