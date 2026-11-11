"""Catalog contract: computed discount, forgiving search, filters and ordering.

Pure domain rules, so no database and no HTTP: products are built in memory.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domains.products.domain.entities import (
    Category,
    Inventory,
    Product,
    ProductVariant,
)
from app.domains.products.domain.search import (
    ProductCriteria,
    ProductSort,
    edit_distance,
    normalize,
    search,
)
from app.shared.exceptions import ValidationError


def _product(
    pid: int,
    name: str,
    price: str,
    *,
    original: str | None = None,
    category: tuple[str, str] = ("Curated Jersey", "curated-jersey"),
    style: str = "Jersey",
    color: str = "Red",
    tone: str = "",
    sizes: tuple[str, ...] = ("M", "L"),
    **flags: bool,
) -> Product:
    return Product(
        id=pid,
        slug=name.lower().replace(" ", "-"),
        name=name,
        category=Category(id=pid, name=category[0], slug=category[1]),
        price=Decimal(price),
        original_price=Decimal(original) if original else None,
        style=style,
        color=color,
        tone=tone,
        variants=[
            ProductVariant(id=pid * 10 + i, sku=f"{pid}-{size}", size=size,
                           inventory=Inventory(quantity=5))
            for i, size in enumerate(sizes)
        ],
        **flags,
    )


@pytest.fixture
def catalog() -> list[Product]:
    return [
        _product(1, "AC Milan 25-26", "58500", original="68000", is_bestseller=True,
                 is_new_arrival=True, tone="Red / Black"),
        _product(2, "Barcelona Away", "62000", original="75000", style="Archive",
                 color="Black", category=("Archive Edition", "archive-edition")),
        _product(3, "Liverpool 25-26", "61500", style="Heritage", sizes=("M", "L", "XL")),
        _product(4, "ZOID Pro Gym Set", "48000", style="Gym Kit", color="Black",
                 category=("Gym Kits", "gym-kits"), sizes=("S", "M", "L", "XL"),
                 is_special=True),
    ]


# ── discount ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("price", "original", "expected"),
    [
        ("58500", "68000", 14),  # 13.97% rounds up
        ("62000", "75000", 17),
        ("64000", "80000", 20),
        ("58500", None, None),
        ("58500", "58500", None),  # not actually cheaper
        ("99900", "100000", None),  # < 1% is not advertised
    ],
)
def test_discount_percent_is_derived_from_the_two_prices(
    price: str, original: str | None, expected: int | None
) -> None:
    product = Product(
        id=1, slug="s", name="n", category=Category(id=1, name="c", slug="c"),
        price=Decimal(price),
        original_price=Decimal(original) if original else None,
    )
    # Bypass validate(): the equal-price case is rejected there, but the
    # property must still be safe on any value it is handed.
    assert product.discount_percent == expected


def test_original_price_at_or_below_price_is_rejected() -> None:
    product = _product(1, "Shirt", "50000", original="50000")
    with pytest.raises(ValidationError, match="Original price"):
        product.validate()


def test_edit_can_move_price_and_clear_original_atomically() -> None:
    product = _product(1, "Shirt", "50000", original="60000")
    product.apply_details({"price": Decimal("70000"), "original_price": None})
    assert product.original_price is None
    assert product.discount_percent is None


def test_failed_edit_leaves_the_product_unchanged() -> None:
    product = _product(1, "Shirt", "50000", original="60000")
    with pytest.raises(ValidationError):
        product.apply_details({"price": Decimal("70000")})  # now above original
    assert product.price == Decimal("50000")


# ── normalising / edit distance ─────────────────────────────────────────


def test_normalize_strips_punctuation_and_accents() -> None:
    assert normalize("  Lyon / 25—26 ") == "lyon 25 26"
    assert normalize("Atlético") == "atletico"


def test_edit_distance() -> None:
    assert edit_distance("liverpol", "liverpool") == 1
    assert edit_distance("abc", "abc") == 0


# ── search ──────────────────────────────────────────────────────────────


def test_empty_criteria_returns_the_whole_catalog_oldest_first(catalog: list[Product]) -> None:
    assert [p.id for p in search(catalog, ProductCriteria())] == [1, 2, 3, 4]


def test_search_forgives_typos(catalog: list[Product]) -> None:
    assert [p.id for p in search(catalog, ProductCriteria(query="liverpol"))] == [3]
    assert [p.id for p in search(catalog, ProductCriteria(query="barcalona"))] == [2]


def test_search_matches_style_colour_and_category_words(catalog: list[Product]) -> None:
    assert [p.id for p in search(catalog, ProductCriteria(query="gym"))] == [4]
    assert 2 in [p.id for p in search(catalog, ProductCriteria(query="archive"))]


def test_nonsense_query_matches_nothing(catalog: list[Product]) -> None:
    assert search(catalog, ProductCriteria(query="xqzvbn")) == []


def test_better_matches_rank_first(catalog: list[Product]) -> None:
    results = search(catalog, ProductCriteria(query="black archive"))
    assert results[0].id == 2  # matches both words


# ── filters ─────────────────────────────────────────────────────────────


def test_filters_are_case_insensitive_and_combine(catalog: list[Product]) -> None:
    assert [p.id for p in search(catalog, ProductCriteria(color="BLACK"))] == [2, 4]
    assert [p.id for p in search(catalog, ProductCriteria(color="black", style="gym kit"))] == [4]
    assert [p.id for p in search(catalog, ProductCriteria(category="gym-kits"))] == [4]


def test_size_filter_matches_offered_sizes(catalog: list[Product]) -> None:
    assert [p.id for p in search(catalog, ProductCriteria(size="xl"))] == [3, 4]
    assert [p.id for p in search(catalog, ProductCriteria(size="S"))] == [4]


def test_price_range(catalog: list[Product]) -> None:
    criteria = ProductCriteria(min_price=Decimal("50000"), max_price=Decimal("60000"))
    assert [p.id for p in search(catalog, criteria)] == [1]


def test_flag_filters(catalog: list[Product]) -> None:
    assert [p.id for p in search(catalog, ProductCriteria(bestseller=True))] == [1]
    assert [p.id for p in search(catalog, ProductCriteria(special=True))] == [4]
    assert [p.id for p in search(catalog, ProductCriteria(new_arrival=True))] == [1]
    assert [p.id for p in search(catalog, ProductCriteria(on_sale=True))] == [1, 2]
    assert [p.id for p in search(catalog, ProductCriteria(on_sale=False))] == [3, 4]


# ── ordering ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("sort", "expected"),
    [
        (ProductSort.OLDEST, [1, 2, 3, 4]),
        (ProductSort.NEWEST, [4, 3, 2, 1]),
        (ProductSort.PRICE_ASC, [4, 1, 3, 2]),
        (ProductSort.PRICE_DESC, [2, 3, 1, 4]),
        (ProductSort.NAME, [1, 2, 3, 4]),
    ],
)
def test_sort_orders(catalog: list[Product], sort: ProductSort, expected: list[int]) -> None:
    assert [p.id for p in search(catalog, ProductCriteria(sort=sort))] == expected


# ── stock corrections (the inventory rules behind the admin endpoint) ───


def _stock(quantity: int, reserved: int = 0) -> Inventory:
    return Inventory(quantity=quantity, reserved=reserved)


def test_stock_can_be_corrected_down_as_well_as_up() -> None:
    inventory = _stock(10)
    inventory.adjust(-3)
    assert inventory.quantity == 7
    inventory.adjust(5)
    assert inventory.quantity == 12


def test_a_correction_cannot_take_stock_from_under_a_promised_order() -> None:
    inventory = _stock(10, reserved=4)

    inventory.adjust(-6)  # exactly down to what is promised is fine
    assert (inventory.quantity, inventory.available) == (4, 0)

    with pytest.raises(ValidationError, match="reserved"):
        inventory.adjust(-1)
    assert inventory.quantity == 4  # unchanged by the refusal


def test_stock_cannot_go_below_zero() -> None:
    with pytest.raises(ValidationError, match="below zero"):
        _stock(2).adjust(-3)


def test_a_zero_adjustment_is_refused_but_confirming_a_count_is_fine() -> None:
    with pytest.raises(ValidationError, match="change the count"):
        _stock(5).adjust(0)
    inventory = _stock(5)
    inventory.set_quantity(5)  # a stock-take that agrees with the books
    assert inventory.quantity == 5


def test_a_stock_take_sets_the_count_outright_under_the_same_rules() -> None:
    inventory = _stock(10, reserved=3)
    inventory.set_quantity(20)
    assert inventory.quantity == 20
    inventory.set_quantity(3)
    assert inventory.quantity == 3
    with pytest.raises(ValidationError, match="reserved"):
        inventory.set_quantity(2)
