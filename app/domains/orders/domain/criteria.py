"""What the shop can ask of the order book.

A plain description of a question ("paid orders in transit, placed this week,
mentioning Ada"), kept free of SQL so the same question can be answered by any
storage and tested without one. Every field is optional; an empty criteria is the
whole book.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domains.orders.domain.entities import Order
from app.domains.orders.domain.enums import FulfillmentStatus, OrderPaymentStatus


@dataclass(frozen=True)
class OrderCriteria:
    payment_status: OrderPaymentStatus | None = None
    fulfillment_status: FulfillmentStatus | None = None
    #: standard / express / pickup — how the order is to reach the customer.
    delivery_option: str | None = None
    #: Matches the order reference or the customer's name, email or phone.
    query: str = ""
    #: Placed at or after this moment.
    created_from: datetime | None = None
    #: Placed *before* this moment (exclusive, so adjoining periods never overlap).
    created_before: datetime | None = None

    def matches(self, order: Order) -> bool:
        """Does ``order`` answer this question?

        The definition every storage has to agree with: the SQL repository maps
        each clause to columns, and a test holds the two to the same answers.
        """
        if self.payment_status is not None and order.payment_status is not self.payment_status:
            return False
        if (
            self.fulfillment_status is not None
            and order.fulfillment_status is not self.fulfillment_status
        ):
            return False
        if self.delivery_option and order.delivery_option != self.delivery_option:
            return False
        needle = self.query.strip().casefold()
        if needle and not any(
            needle in field.casefold()
            for field in (
                order.reference,
                order.contact_name,
                order.contact_email,
                order.contact_phone,
            )
        ):
            return False
        if self.created_from is not None and (
            order.created_at is None or order.created_at < self.created_from
        ):
            return False
        return not (
            self.created_before is not None
            and (order.created_at is None or order.created_at >= self.created_before)
        )
