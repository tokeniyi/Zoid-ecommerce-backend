"""Product catalog domain entities and business rules.

Plain, framework-free objects. Validation lives here as explicit ``validate()``
rules (raised as the shared ``ValidationError``) so it is enforced on the write
path and unit-testable without any database or HTTP involvement — reads of
existing rows do not re-run them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from app.shared.exceptions import ValidationError

IMAGE_VIEWS = frozenset({"front", "back", "detail"})

#: At or below this many sellable units a product is one the shop has to restock.
#: The storefront's own admin screen counts with the same number.
LOW_STOCK_THRESHOLD = 5


class StockStatus(StrEnum):
    """How a product stands as stock, seen from the shop side."""

    OUT_OF_STOCK = "out_of_stock"
    LOW_STOCK = "low_stock"
    IN_STOCK = "in_stock"

#: Product properties an administrator may edit after a product exists. Identity
#: (``id``, ``slug``) and the variant/image *structure* are deliberately absent:
#: a variant list is fixed when the product is created, and restocking is the
#: separate ``receive`` operation below.
EDITABLE_PRODUCT_FIELDS = (
    "name",
    "price",
    "currency",
    "tone",
    "style",
    "color",
    "fit",
    "fit_note",
    "details",
    "delivery",
    "is_bestseller",
    "is_special",
    "is_active",
)


@dataclass(frozen=True)
class Category:
    """A catalog grouping for products."""

    id: int
    name: str
    slug: str

    def validate(self) -> None:
        if not self.name.strip():
            raise ValidationError("Category name is required.")
        if not self.slug.strip():
            raise ValidationError("Category slug is required.")


@dataclass(frozen=True)
class ProductImage:
    """One gallery image; ``view`` is front/back/detail."""

    url: str
    view: str = "front"

    def validate(self) -> None:
        if not self.url.strip():
            raise ValidationError("Product image URL is required.")
        if self.view not in IMAGE_VIEWS:
            raise ValidationError(f"Invalid image view: {self.view!r}.")


@dataclass
class Inventory:
    """Stock counts for a single variant."""

    quantity: int = 0
    reserved: int = 0

    @property
    def available(self) -> int:
        return self.quantity - self.reserved

    def receive(self, quantity: int) -> None:
        """Take newly stocked units in (an admin restock).

        Stock can only ever go up by a real amount here: restocking is how a
        sold-out size comes back, and the store never receives zero units.
        Nothing reserved is disturbed.
        """
        if quantity < 1:
            raise ValidationError("Stock increase must be a positive quantity.")
        self.quantity += quantity
        self.validate()

    def validate(self) -> None:
        if self.quantity < 0:
            raise ValidationError("Inventory quantity cannot be negative.")
        if self.reserved < 0:
            raise ValidationError("Inventory reservation cannot be negative.")
        if self.reserved > self.quantity:
            raise ValidationError("Reserved stock cannot exceed available quantity.")


@dataclass
class ProductVariant:
    """A purchasable size variant of a product, carrying its inventory."""

    id: int
    sku: str
    size: str
    inventory: Inventory = field(default_factory=Inventory)

    def validate(self) -> None:
        if not self.sku.strip():
            raise ValidationError("Variant SKU is required.")
        if not self.size.strip():
            raise ValidationError("Variant size is required.")
        self.inventory.validate()


@dataclass
class Product:
    """A catalog product and its images, variants and inventory."""

    id: int
    slug: str
    name: str
    category: Category
    price: Decimal
    currency: str = "NGN"
    images: list[ProductImage] = field(default_factory=list)
    variants: list[ProductVariant] = field(default_factory=list)
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
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def sizes(self) -> list[str]:
        return [variant.size for variant in self.variants]

    @property
    def stock(self) -> dict[str, int]:
        return {variant.size: variant.inventory.available for variant in self.variants}

    @property
    def primary_image(self) -> str | None:
        return self.images[0].url if self.images else None

    @property
    def units_available(self) -> int:
        """Sellable units across every size — what a shopkeeper reads as stock."""
        return sum(variant.inventory.available for variant in self.variants)

    @property
    def stock_status(self) -> StockStatus:
        """Classify the whole product on its sellable units.

        A size that has run out is a problem for a product that still has others,
        but the shop-level question the dashboard asks is whether the product as a
        whole needs restocking, so the sizes are counted together.
        """
        units = self.units_available
        if units <= 0:
            return StockStatus.OUT_OF_STOCK
        if units <= LOW_STOCK_THRESHOLD:
            return StockStatus.LOW_STOCK
        return StockStatus.IN_STOCK

    def find_variant(self, size: str) -> ProductVariant | None:
        """The variant for ``size``, matched case-insensitively on the label."""
        wanted = size.strip().casefold()
        return next(
            (variant for variant in self.variants if variant.size.strip().casefold() == wanted),
            None,
        )

    def apply_details(self, changes: dict[str, object]) -> None:
        """Apply an admin edit; a field that was not sent stays as it is.

        Only :data:`EDITABLE_PRODUCT_FIELDS` can be changed here, and the result
        has to satisfy the product rules, so an edit can never leave a product
        that the catalog would refuse to have created — a rejected edit leaves the
        product exactly as it was rather than half-changed.
        """
        unknown = set(changes) - set(EDITABLE_PRODUCT_FIELDS)
        if unknown:
            raise ValidationError(f"Not editable on a product: {sorted(unknown)}.")
        before = {name: getattr(self, name) for name in changes}
        try:
            for field_name, value in changes.items():
                setattr(self, field_name, value)
            self.validate()
        except ValidationError:
            for name, value in before.items():
                setattr(self, name, value)
            raise

    def validate(self) -> None:
        if not self.slug.strip():
            raise ValidationError("Product slug is required.")
        if not self.name.strip():
            raise ValidationError("Product name is required.")
        if self.price < 0:
            raise ValidationError("Product price cannot be negative.")
        if not self.currency.strip():
            raise ValidationError("Product currency is required.")
        self.category.validate()
        for image in self.images:
            image.validate()
        for variant in self.variants:
            variant.validate()
