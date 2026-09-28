"""Order lifecycle status.

Payment status is a *separate* concept (see the payments domain): an order is
created in :attr:`OrderStatus.PENDING_PAYMENT` and only becomes ``PAID`` when a
payment is verified, never because an HTTP endpoint returned success.
"""

from __future__ import annotations

from enum import StrEnum


class OrderStatus(StrEnum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PAID = "PAID"
    PROCESSING = "PROCESSING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
