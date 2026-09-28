"""Post-payment notifications: what the store tells itself when money arrives.

Two separable questions live around this seam, and they are kept apart on
purpose:

* *What to say* is e-commerce knowledge -- an order number, a customer, the lines
  that were bought, where the parcel goes. That is composed here, next to the
  order it describes, into an ordinary :class:`EmailMessage`.
* *How to send it* belongs to an email provider adapter, which is handed a
  message and never learns that a shop, a jersey or a payment exists.

So the payment service asks for one thing -- "notify me about this paid order" --
and the notification asks one thing of the email capability -- "send this".
Neither ends up knowing which provider was configured.

Delivery is reported, never raised. By the time this runs the money has arrived
and the order is paid; an email that cannot be sent is news for a log, not a
reason to undo a confirmed payment.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal

from app.domains.orders.domain.entities import Order
from app.domains.payments.domain.entities import Transaction
from app.integrations.email.sender import (
    AbstractEmailSender,
    EmailMessage,
    is_email_address,
)

logger = logging.getLogger(__name__)


def _money(amount: Decimal, currency: str) -> str:
    return f"{amount:,.2f} {currency}"


def _moment(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else "not recorded"


def _order_lines(order: Order, transaction: Transaction) -> Iterator[str]:
    """The email body, as the store owner needs to read it."""
    yield f"Order {order.reference} has been paid."
    yield ""
    yield "Order"
    yield f"  Number:  {order.reference}"
    yield f"  Status:  {order.status.value}"
    yield f"  Placed:  {_moment(order.created_at)}"
    yield ""
    yield "Customer"
    yield f"  Name:  {order.contact_name}"
    yield f"  Email: {order.contact_email}"
    yield f"  Phone: {order.contact_phone or 'not given'}"
    yield ""
    yield "Items"
    for item in order.items:
        yield (
            f"  {item.quantity} x {item.product_name} (size {item.size}) "
            f"at {_money(item.unit_price, item.currency)} "
            f"= {_money(item.line_total, item.currency)}"
        )
    yield ""
    yield f"Total  {_money(order.total, order.currency)}"
    yield ""
    yield "Delivery"
    yield f"  Address: {order.address_line}"
    yield f"  City/State: {order.city_state or 'not given'}"
    yield f"  Notes: {order.notes or 'none'}"
    yield ""
    yield "Payment"
    yield f"  Reference: {transaction.reference}"
    yield f"  Amount:    {_money(transaction.amount, transaction.currency)}"
    yield f"  Provider:  {transaction.provider}"
    yield f"  Provider reference: {transaction.provider_reference or 'not reported'}"


def build_order_notification(
    order: Order, transaction: Transaction, *, owner_email: str
) -> EmailMessage:
    """The store-owner email for one paid order."""
    return EmailMessage(
        to=owner_email,
        subject=f"Paid order {order.reference} - {_money(order.total, order.currency)}",
        text_body="\n".join(_order_lines(order, transaction)),
    )


class PaidOrderNotifier:
    """Tells the store owner about a paid order, through the email contract."""

    def __init__(self, *, sender: AbstractEmailSender, owner_email: str) -> None:
        # The contract, not a provider: this class is what a payment service is
        # allowed to know about email.
        self._sender = sender
        self._owner_email = owner_email

    @property
    def provider(self) -> str:
        return self._sender.provider

    async def notify_paid(
        self, *, order: Order, transaction: Transaction
    ) -> bool:
        """Send the owner's order email. Returns whether it was delivered.

        A store with no owner address configured simply does not notify: that is
        a deployment choice, not a failure of a payment. Everything else that can
        go wrong -- a provider that is unconfigured, unreachable or unhappy with
        the message -- is caught here for one reason. The order is already paid;
        nothing an email can do gets to change that.
        """
        if not is_email_address(self._owner_email):
            logger.warning(
                "Order %s is paid but no store owner email is configured; "
                "no notification sent.",
                order.reference,
            )
            return False

        message = build_order_notification(
            order, transaction, owner_email=self._owner_email
        )
        try:
            delivery = await self._sender.send(message)
        except Exception:
            logger.exception(
                "Email provider '%s' raised while notifying order %s.",
                self._sender.provider,
                order.reference,
            )
            return False
        if not delivery.success:
            logger.error(
                "Could not notify the store owner about order %s: %s",
                order.reference,
                delivery.message or "the provider gave no reason",
            )
            return False
        return True
