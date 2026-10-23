"""Money values at the HTTP boundary.

Domain and persistence code use :class:`~decimal.Decimal`.  JSON numbers are
binary floating-point values in most clients, so API responses use fixed-scale
decimal strings instead (for example, ``"58500.00"``).
"""

from decimal import Decimal


_MONEY_PLACES = Decimal("0.01")


def serialize_money(value: Decimal) -> str:
    """Return a two-decimal string without converting money through ``float``."""
    return format(value.quantize(_MONEY_PLACES), ".2f")
