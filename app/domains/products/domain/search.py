"""Catalog search, filters and ordering — pure domain rules.

The storefront's search is *forgiving*: "barca" or "liverpol" should still find
the shirt the shopper meant. That behaviour is a catalog rule, not a transport
or persistence detail, so it lives here as plain functions over
:class:`~app.domains.products.domain.entities.Product` — unit-testable with no
database and identical wherever the catalog is read (storefront or admin).

The matcher is a port of the storefront's own ``searchProducts`` so that moving
the search behind the API does not change what a shopper finds: tokens are
compared by containment or by edit distance (at most 2, on words of 5+
letters), and a product needs a score of at least :data:`MIN_SCORE` to appear.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.domains.products.domain.entities import Product

#: A product scoring below this is not a match for the query.
MIN_SCORE = 0.3
#: Bonus when every word of the query matched something.
_ALL_TOKENS_BONUS = 0.18
#: Keeps equally good matches in catalog order.
_ORDER_TIEBREAK = 0.0005
#: Typos only forgiven on words at least this long, and by at most this distance.
_MIN_FUZZY_LENGTH = 5
_MAX_EDIT_DISTANCE = 2

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


class ProductSort(StrEnum):
    """How a catalog listing is ordered."""

    RELEVANCE = "relevance"
    OLDEST = "oldest"
    NEWEST = "newest"
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"
    NAME = "name"


@dataclass(frozen=True)
class ProductCriteria:
    """What a shopper (or the shop) is looking for.

    Every field is optional; an empty criteria means "the whole catalog". Text
    filters compare case-insensitively. ``sort`` left as ``None`` means "the
    natural order for this request": relevance when there is a search query,
    otherwise the order products were added.
    """

    query: str = ""
    category: str | None = None
    style: str | None = None
    color: str | None = None
    size: str | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    bestseller: bool | None = None
    special: bool | None = None
    new_arrival: bool | None = None
    on_sale: bool | None = None
    sort: ProductSort | None = None


def normalize(value: str) -> str:
    """Lower-case, strip accents and punctuation, collapse spaces."""
    decomposed = unicodedata.normalize("NFKD", value.lower())
    # Drop the combining accent marks NFKD splits off ("é" -> "e" + mark), or
    # the punctuation rule below would turn each one into a stray space.
    unaccented = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _NON_ALNUM.sub(" ", unaccented).strip()


def edit_distance(left: str, right: str) -> int:
    """Levenshtein distance between two words."""
    previous = list(range(len(right) + 1))
    for row in range(1, len(left) + 1):
        diagonal = previous[0]
        previous[0] = row
        for column in range(1, len(right) + 1):
            above = previous[column]
            cost = 0 if left[row - 1] == right[column - 1] else 1
            previous[column] = min(previous[column] + 1, previous[column - 1] + 1, diagonal + cost)
            diagonal = above
    return previous[len(right)]


def token_similarity(query_token: str, product_token: str) -> float:
    """0 for unrelated words, up to 1 for containment or a near-miss."""
    if not query_token or not product_token:
        return 0.0
    if query_token in product_token or product_token in query_token:
        return 1.0
    distance = edit_distance(query_token, product_token)
    scale = max(len(query_token), len(product_token))
    if distance <= _MAX_EDIT_DISTANCE and scale >= _MIN_FUZZY_LENGTH:
        return max(0.0, 1 - distance / scale)
    return 0.0


def _searchable_tokens(product: Product) -> list[str]:
    text = " ".join(
        [product.name, product.category.name, product.color, product.style, product.tone]
    )
    return normalize(text).split()


def relevance(product: Product, query: str) -> float:
    """How well ``product`` answers ``query``; below :data:`MIN_SCORE` is a miss."""
    query_tokens = normalize(query).split()
    if not query_tokens:
        return 1.0
    product_tokens = _searchable_tokens(product)
    scores = [
        max((token_similarity(token, candidate) for candidate in product_tokens), default=0.0)
        for token in query_tokens
    ]
    matched = sum(1 for score in scores if score > 0)
    bonus = _ALL_TOKENS_BONUS if matched == len(query_tokens) else 0.0
    return sum(scores) / len(query_tokens) + bonus


def _same(left: str, right: str) -> bool:
    return left.strip().casefold() == right.strip().casefold()


def _passes_filters(product: Product, criteria: ProductCriteria) -> bool:
    if criteria.category is not None and not _same(product.category.slug, criteria.category):
        return False
    if criteria.style is not None and not _same(product.style, criteria.style):
        return False
    if criteria.color is not None and not _same(product.color, criteria.color):
        return False
    if criteria.size is not None and product.find_variant(criteria.size) is None:
        return False
    if criteria.min_price is not None and product.price < criteria.min_price:
        return False
    if criteria.max_price is not None and product.price > criteria.max_price:
        return False
    if criteria.bestseller is not None and product.is_bestseller != criteria.bestseller:
        return False
    if criteria.special is not None and product.is_special != criteria.special:
        return False
    if criteria.new_arrival is not None and product.is_new_arrival != criteria.new_arrival:
        return False
    if criteria.on_sale is not None and (product.discount_percent is not None) != criteria.on_sale:
        return False
    return True


def search(products: Iterable[Product], criteria: ProductCriteria) -> list[Product]:
    """Filter, rank and order ``products`` for ``criteria``.

    ``products`` is taken in catalog order (oldest first), which is also the
    tie-break for equally relevant results.
    """
    catalog = [product for product in products if _passes_filters(product, criteria)]
    has_query = bool(normalize(criteria.query))
    sort = criteria.sort or (ProductSort.RELEVANCE if has_query else ProductSort.OLDEST)

    scores: dict[int, float] = {}
    if has_query:
        for index, product in enumerate(catalog):
            scores[product.id] = relevance(product, criteria.query) - index * _ORDER_TIEBREAK
        catalog = [product for product in catalog if scores[product.id] >= MIN_SCORE]

    if sort is ProductSort.RELEVANCE and has_query:
        return sorted(catalog, key=lambda product: scores[product.id], reverse=True)
    if sort is ProductSort.NEWEST:
        return sorted(catalog, key=lambda product: product.id, reverse=True)
    if sort is ProductSort.PRICE_ASC:
        return sorted(catalog, key=lambda product: (product.price, product.id))
    if sort is ProductSort.PRICE_DESC:
        return sorted(catalog, key=lambda product: (-product.price, product.id))
    if sort is ProductSort.NAME:
        return sorted(catalog, key=lambda product: (product.name.casefold(), product.id))
    return sorted(catalog, key=lambda product: product.id)
