"""Order lifecycle status.

Payment status is a *separate* concept (see the payments domain): an order is
created in :attr:`OrderStatus.PENDING_PAYMENT` and only becomes ``PAID`` when a
payment is verified, never because an HTTP endpoint returned success.
"""

from __future__ import annotations

from enum import StrEnum


class FulfillmentStatus(StrEnum):
    """Where a *paid* order is on its way to the customer.

    Deliberately separate from :class:`OrderStatus`: the order's status answers
    "has it been paid?" and only the payments workflow moves it, so the shop
    updating a parcel can never disturb (or be blocked by) a payment, and a
    payment notification arriving late cannot collide with a parcel in transit.
    """

    PROCESSING = "processing"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"


class OrderPaymentStatus(StrEnum):
    """The payment side of an order, as the customer reads it."""

    PENDING = "pending"
    PAID = "paid"
    CANCELLED = "cancelled"


class OrderStatus(StrEnum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PAID = "PAID"
    PROCESSING = "PROCESSING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
