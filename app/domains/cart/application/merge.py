"""Merge strategies for folding a guest cart into an authenticated cart.

The architecture leaves the duplicate/conflict behaviour during merge
**Not Specified**, so it is isolated behind ``AbstractCartMergeStrategy`` and can
be replaced without touching the rest of the cart flow. ``AdditiveMergeStrategy``
is a provisional default (see its docstring), not an authoritative rule.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domains.cart.domain.entities import Cart


class AbstractCartMergeStrategy(ABC):
    """Defines how ``source`` guest items are folded into ``target`` user items."""

    @abstractmethod
    def merge(self, target: Cart, source: Cart) -> None:
        """Mutate ``target`` in place to incorporate ``source`` items."""


class AdditiveMergeStrategy(AbstractCartMergeStrategy):
    """PROVISIONAL DEFAULT — not an authoritative conflict policy.

    Moves every guest line into the target cart via ``Cart.add_item`` which, when
    the same variant is already present, sums the quantities. Whether duplicates
    should instead be capped, replaced, or surfaced for the shopper to resolve is
    **Not Specified in the architecture** and must be decided before this default
    is treated as final. Swap it by injecting a different strategy into
    :class:`app.domains.cart.application.service.CartService`.
    """

    def merge(self, target: Cart, source: Cart) -> None:
        for item in list(source.items):
            # Re-home the line on the target as a fresh entry; ``add_item`` then
            # either appends it or folds it into an existing matching variant.
            item.id = 0
            target.add_item(item)
