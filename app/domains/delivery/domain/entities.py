"""Delivery: how an order reaches the customer, and what that costs.

Plain, framework-free objects. The *server* prices delivery — the browser sends
where it wants the order to go and never an amount — so every figure comes from
a :class:`DeliveryRate` the shop has set, chosen by the rules in
:mod:`app.domains.delivery.domain.rules`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.shared.exceptions import ValidationError


class DeliveryOption(StrEnum):
    """The ways the storefront offers to get an order to a customer."""

    #: Hand delivery to a door or a university hostel.
    STANDARD = "standard"
    #: Prioritised hand delivery.
    EXPRESS = "express"
    #: Collect from a GUO Transport terminal.
    PICKUP = "pickup"
    #: "Not sure / not listed" — arranged with the shop directly, never priced here.
    ENQUIRY = "enquiry"


@dataclass(frozen=True)
class DeliveryRate:
    """One pricing rule: *for this option, at this place, the fee is this*.

    A field left ``None`` means "anywhere". The more fields a rate pins down, the
    more specific it is, and the most specific rate that fits wins:

    ``terminal`` > ``university`` > ``city`` > ``state`` > nothing at all.
    """

    id: int
    option: DeliveryOption
    fee: Decimal
    state: str | None = None
    city: str | None = None
    university: str | None = None
    terminal: str | None = None
    is_active: bool = True

    @property
    def specificity(self) -> int:
        if self.terminal is not None:
            return 4
        if self.university is not None:
            return 3
        if self.city is not None:
            return 2
        if self.state is not None:
            return 1
        return 0

    @property
    def key(self) -> str:
        """Natural identity, so seeding the same rule twice is a no-op."""
        parts = (self.option.value, self.state, self.city, self.university, self.terminal)
        return "|".join((part or "").strip().casefold() for part in parts)

    def validate(self) -> None:
        if self.fee < 0:
            raise ValidationError("A delivery fee cannot be negative.")


@dataclass(frozen=True)
class DeliveryDetails:
    """Where the customer wants the order to go, as the checkout form collects it."""

    option: DeliveryOption
    state: str = ""
    city: str = ""
    address: str = ""
    university: str = ""
    hostel_room: str = ""
    terminal: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        # Accept the plain string ("standard") as well as the enum, so no caller
        # can hand in a value the identity checks below would silently miss.
        object.__setattr__(self, "option", DeliveryOption(self.option))

    @property
    def is_student(self) -> bool:
        """Delivered to a campus rather than an address."""
        return self.option is DeliveryOption.STANDARD and bool(self.university.strip())

    def validate(self) -> None:
        """Whether the form is complete for the option chosen."""
        if self.option is DeliveryOption.STANDARD:
            if self.is_student:
                if not self.hostel_room.strip():
                    raise ValidationError("Campus delivery needs a hostel and room.")
            else:
                for name, value in (
                    ("address", self.address),
                    ("city", self.city),
                    ("state", self.state),
                ):
                    if not value.strip():
                        raise ValidationError(f"Home delivery needs a {name}.")
        elif self.option is DeliveryOption.EXPRESS:
            for name, value in (
                ("address", self.address),
                ("city", self.city),
                ("state", self.state),
            ):
                if not value.strip():
                    raise ValidationError(f"Express delivery needs a {name}.")
        elif self.option is DeliveryOption.PICKUP:
            if not self.state.strip():
                raise ValidationError("Terminal pickup needs a state.")
            if not self.terminal.strip():
                raise ValidationError("Terminal pickup needs a terminal.")


@dataclass(frozen=True)
class DeliveryQuote:
    """What delivering to a place costs, or that the shop has to be asked."""

    option: DeliveryOption
    fee: Decimal | None
    state: str
    city: str
    university: str
    terminal: str
    #: ``True`` when no rate covers this place: no price is invented, the
    #: customer is pointed at the shop instead.
    support_required: bool
    #: Pickup at a terminal the shop has not verified yet; the shop confirms it.
    terminal_pending: bool
    message: str
    rate_id: int | None = None

    @property
    def is_priced(self) -> bool:
        return self.fee is not None and not self.support_required
