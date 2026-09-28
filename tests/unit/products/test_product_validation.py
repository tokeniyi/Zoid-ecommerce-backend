"""Domain business-rule validation — product, variant, inventory, image.

Proves the catalog rules are enforced in the domain, with no database or HTTP.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domains.products.domain.entities import (
    LOW_STOCK_THRESHOLD,
    Category,
    Inventory,
    Product,
    ProductImage,
    ProductVariant,
    StockStatus,
)
from app.shared.exceptions import ValidationError


def _product(**overrides: object) -> Product:
    base: dict[str, object] = {
        "id": 0,
        "slug": "ac-milan-2526",
        "name": "AC Milan / 25—26",
        "category": Category(id=1, name="Curated Jersey", slug="curated-jersey"),
        "price": Decimal("58500.00"),
        "images": [ProductImage(url="/i/front.jpg", view="front")],
        "variants": [
            ProductVariant(id=1, sku="ACM-M", size="M", inventory=Inventory(quantity=8))
        ],
    }
    base.update(overrides)
    return Product(**base)  # type: ignore[arg-type]


def test_valid_product_passes_validation() -> None:
    _product().validate()  # must not raise


def test_product_requires_name_and_slug() -> None:
    with pytest.raises(ValidationError):
        _product(name="   ").validate()
    with pytest.raises(ValidationError):
        _product(slug="").validate()


def test_product_price_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        _product(price=Decimal("-1")).validate()


def test_product_currency_required() -> None:
    with pytest.raises(ValidationError):
        _product(currency="  ").validate()


def test_variant_requires_size_and_sku() -> None:
    with pytest.raises(ValidationError):
        _product(
            variants=[ProductVariant(id=1, sku=" ", size="M", inventory=Inventory())]
        ).validate()
    with pytest.raises(ValidationError):
        _product(
            variants=[ProductVariant(id=1, sku="ACM-M", size=" ", inventory=Inventory())]
        ).validate()


def test_inventory_quantity_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        Inventory(quantity=-1).validate()


def test_inventory_reserved_cannot_exceed_quantity() -> None:
    with pytest.raises(ValidationError):
        Inventory(quantity=2, reserved=5).validate()


def test_inventory_available_is_quantity_minus_reserved() -> None:
    assert Inventory(quantity=10, reserved=3).available == 7


def test_propagates_variant_inventory_rule_through_product() -> None:
    product = _product(
        variants=[
            ProductVariant(id=1, sku="ACM-L", size="L", inventory=Inventory(quantity=1, reserved=4))
        ]
    )
    with pytest.raises(ValidationError):
        product.validate()


def test_image_rejects_unknown_view() -> None:
    with pytest.raises(ValidationError):
        _product(images=[ProductImage(url="/i/x.jpg", view="side")]).validate()


def test_image_requires_url() -> None:
    with pytest.raises(ValidationError):
        _product(images=[ProductImage(url="  ", view="front")]).validate()


def test_stock_and_sizes_derive_from_variants() -> None:
    product = _product(
        variants=[
            ProductVariant(
                id=1,
                sku="ACM-M",
                size="M",
                inventory=Inventory(quantity=8, reserved=2),
            ),
            ProductVariant(id=2, sku="ACM-L", size="L", inventory=Inventory(quantity=3)),
        ]
    )
    assert product.sizes == ["M", "L"]
    assert product.stock == {"M": 6, "L": 3}  # available, not raw quantity


# ── Rules the shop side leans on (admin restock, edit, dashboard) ────


def test_receiving_stock_adds_units_without_disturbing_what_is_promised() -> None:
    inventory = Inventory(quantity=2, reserved=2)

    inventory.receive(5)

    assert (inventory.quantity, inventory.reserved, inventory.available) == (7, 2, 5)


@pytest.mark.parametrize("quantity", [0, -1, -50])
def test_receiving_stock_has_to_be_real_stock(quantity: int) -> None:
    inventory = Inventory(quantity=3)

    with pytest.raises(ValidationError):
        inventory.receive(quantity)

    assert inventory.quantity == 3


def test_a_product_is_out_of_stock_only_when_every_size_is_gone() -> None:
    assert _product(variants=[]).stock_status is StockStatus.OUT_OF_STOCK
    sold_out = ProductVariant(
        id=1, sku="ACM-M", size="M", inventory=Inventory(quantity=1, reserved=1)
    )
    assert _product(variants=[sold_out]).stock_status is StockStatus.OUT_OF_STOCK


def test_running_low_is_counted_across_the_sizes_of_a_product() -> None:
    just_a_few = ProductVariant(
        id=1, sku="ACM-M", size="M", inventory=Inventory(quantity=LOW_STOCK_THRESHOLD)
    )
    plenty = ProductVariant(id=2, sku="ACM-L", size="L", inventory=Inventory(quantity=20))

    assert _product(variants=[just_a_few]).stock_status is StockStatus.LOW_STOCK
    # One size is thin but the product as a whole is not: the shop restocks the
    # size, and the dashboard does not shout about the product.
    assert _product(variants=[just_a_few, plenty]).stock_status is StockStatus.IN_STOCK
    assert _product(variants=[just_a_few, plenty]).units_available == 25


def test_a_size_is_found_whatever_way_it_is_spelled() -> None:
    product = _product()

    assert product.find_variant("m") is product.variants[0]
    assert product.find_variant("  M  ") is product.variants[0]
    assert product.find_variant("XXL") is None


def test_editing_a_product_cannot_touch_its_identity_or_its_sizes() -> None:
    product = _product()

    with pytest.raises(ValidationError):
        product.apply_details({"slug": "somewhere-else"})
    with pytest.raises(ValidationError):
        product.apply_details({"variants": []})


def test_an_edit_that_breaks_a_rule_leaves_the_product_alone() -> None:
    product = _product()

    with pytest.raises(ValidationError):
        product.apply_details({"name": "Renamed", "price": Decimal("-1")})

    assert product.name == "AC Milan / 25—26"
    assert product.price == Decimal("58500.00")


def test_an_edit_is_refused_whole_or_applied_whole() -> None:
    """Naming one thing that cannot be edited refuses the edit before any of it
    is written: a half-applied edit is the thing an admin should never see."""
    product = _product()

    with pytest.raises(ValidationError):
        product.apply_details({"currency": "USD", "created_at": None})

    assert product.currency == "NGN"


def test_an_edit_keeps_everything_it_does_not_name() -> None:
    product = _product()

    product.apply_details({"price": Decimal("60000.00"), "is_bestseller": True})

    assert product.price == Decimal("60000.00")
    assert product.is_bestseller is True
    assert product.name == "AC Milan / 25—26"
    assert product.slug == "ac-milan-2526"
    assert product.stock == {"M": 8}
