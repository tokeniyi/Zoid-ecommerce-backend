"""Delivery HTTP schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.domains.delivery.domain.entities import DeliveryDetails, DeliveryOption, DeliveryQuote
from app.shared.money import serialize_money


class DeliveryRequest(BaseModel):
    """Where the order should go. There is deliberately no amount here: the
    server prices delivery."""

    option: DeliveryOption
    state: str = Field(default="", max_length=80)
    city: str = Field(default="", max_length=120)
    address: str = Field(default="", max_length=300)
    university: str = Field(default="", max_length=200)
    hostel_room: str = Field(default="", max_length=120)
    terminal: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=500)

    def to_details(self) -> DeliveryDetails:
        return DeliveryDetails(**self.model_dump())


class DeliveryQuoteResponse(BaseModel):
    option: DeliveryOption
    #: ``null`` when ``support_required`` is true: no price is invented.
    fee: str | None
    currency: str
    is_student: bool
    state: str
    city: str
    university: str
    terminal: str
    terminal_pending: bool
    support_required: bool
    message: str


def serialize_quote(
    quote: DeliveryQuote, *, currency: str, is_student: bool
) -> DeliveryQuoteResponse:
    return DeliveryQuoteResponse(
        option=quote.option,
        fee=serialize_money(quote.fee) if quote.fee is not None else None,
        currency=currency,
        is_student=is_student,
        state=quote.state,
        city=quote.city,
        university=quote.university,
        terminal=quote.terminal,
        terminal_pending=quote.terminal_pending,
        support_required=quote.support_required,
        message=quote.message,
    )
