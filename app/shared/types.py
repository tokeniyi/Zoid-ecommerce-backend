"""Shared type aliases and small value types."""

from __future__ import annotations

from decimal import Decimal
from typing import NewType

# Identifier aliases improve readability across service/repository boundaries.
UserID = NewType("UserID", int)
ProductID = NewType("ProductID", int)
OrderID = NewType("OrderID", int)
CartID = NewType("CartID", int)

# Money is always represented as Decimal to avoid float rounding on currency.
Money = Decimal

__all__ = ["UserID", "ProductID", "OrderID", "CartID", "Money"]
