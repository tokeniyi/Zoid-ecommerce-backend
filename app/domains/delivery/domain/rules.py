"""Delivery pricing rules — pure functions, no database, no HTTP.

Ported from the storefront's own eligibility logic so that moving the decision to
the server does not change which places are served: hand delivery in Lagos, Ogun
and Port Harcourt, terminal pickup anywhere, and "ask us" for everything else.
What *is* new is that prices come from rate rows, chosen by how specifically they
match the place, instead of constants in the browser.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal

from app.domains.delivery.domain.entities import (
    DeliveryDetails,
    DeliveryOption,
    DeliveryQuote,
    DeliveryRate,
)

#: Where a bare "Rivers" is assumed to mean, as in the storefront.
DEFAULT_RIVERS_CITY = "Port Harcourt"

#: Exact aliases (lower-case) → canonical state name.
STATE_ALIASES = {
    "lagos": "Lagos State",
    "ogun": "Ogun State",
    "rivers": "Rivers State",
    "port harcourt": "Rivers State",
    "ph": "Rivers State",
    "fct": "FCT - Abuja",
    "abuja": "FCT - Abuja",
    "fct - abuja": "FCT - Abuja",
}

#: Words that, found anywhere in what was typed, identify a state.
_STATE_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("lagos",), "Lagos State"),
    (("ogun",), "Ogun State"),
    (("river", "port harcourt"), "Rivers State"),
    (("abuja", "fct"), "FCT - Abuja"),
    (("oyo", "ibadan"), "Oyo State"),
    (("anambra",), "Anambra State"),
    (("enugu",), "Enugu State"),
    (("delta", "warri", "asaba"), "Delta State"),
    (("edo", "benin"), "Edo State"),
    (("kano",), "Kano State"),
    (("kaduna",), "Kaduna State"),
    (("akwa ibom", "uyo"), "Akwa Ibom State"),
)

_WORD = re.compile(r"[^a-z0-9]+")


def _plain(value: str) -> str:
    return _WORD.sub(" ", value.casefold()).strip()


def normalize_state(raw: str) -> str:
    """Canonical state name for whatever the shopper typed ("lagos", "PH", …)."""
    clean = raw.strip()
    if not clean:
        return ""
    lower = clean.casefold()
    if lower in STATE_ALIASES:
        return STATE_ALIASES[lower]
    for words, state in _STATE_KEYWORDS:
        if any(word in lower for word in words):
            return state
    if re.search(r"\bph\b", lower):
        return "Rivers State"
    # Already a state name we do not special-case: just tidy the capitalisation.
    return clean[0].upper() + clean[1:]


def same_place(left: str, right: str) -> bool:
    """Equal names, or one is a whole-word part of the other ("Ikeja" ~ "Ikeja GRA").

    Whole words, not substrings: "Elele" is not "Elelenwo", even though one
    string contains the other. (The storefront used substring matching, which
    would have offered Port Harcourt hand delivery to a different town.)
    """
    a, b = _plain(left), _plain(right)
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = sorted((a, b), key=len)
    return len(shorter) >= 3 and set(shorter.split()) <= set(longer.split())


def _equal(left: str | None, right: str) -> bool:
    return _plain(left or "") == _plain(right)


def _applies(rate: DeliveryRate, state: str, city: str, university: str, terminal: str) -> bool:
    """Does ``rate`` cover this place? Every field it pins down has to fit."""
    if rate.state is not None and normalize_state(rate.state) != state:
        return False
    if rate.city is not None and not same_place(rate.city, city):
        return False
    if rate.university is not None and not _equal(rate.university, university):
        return False
    return rate.terminal is None or _equal(rate.terminal, terminal)


def _university_state(rates: Iterable[DeliveryRate], option: DeliveryOption, name: str) -> str:
    """The state a campus is in, known from the rate the shop set for it."""
    for rate in rates:
        if rate.option is option and rate.university is not None and _equal(rate.university, name):
            return normalize_state(rate.state or "")
    return ""


def quote(details: DeliveryDetails, rates: Iterable[DeliveryRate]) -> DeliveryQuote:
    """Price ``details`` against the shop's rates.

    The most specific rate that fits wins; with none, the answer is "ask the
    shop" — never a made-up price.
    """
    active = [rate for rate in rates if rate.is_active and rate.option is details.option]

    state = normalize_state(details.state)
    city = details.city.strip()
    university = details.university.strip() if details.is_student else ""
    terminal = details.terminal.strip() if details.option is DeliveryOption.PICKUP else ""

    if university and not state:
        state = _university_state(active, details.option, university)
    if state == "Rivers State" and not university and _plain(city) in ("", "ph"):
        # A bare "Rivers", or "PH", means Port Harcourt (as on the storefront).
        city = DEFAULT_RIVERS_CITY

    if details.option is DeliveryOption.ENQUIRY:
        return DeliveryQuote(
            option=details.option, fee=None, state=state, city=city, university="",
            terminal="", support_required=True, terminal_pending=False,
            message="We will arrange this delivery with you directly.",
        )

    fitting = [r for r in active if _applies(r, state, city, university, terminal)]
    if not fitting:
        return DeliveryQuote(
            option=details.option, fee=None, state=state, city=city, university=university,
            terminal=terminal, support_required=True, terminal_pending=False,
            message=_unserved_message(details.option, state or "this area"),
        )

    best = max(fitting, key=lambda rate: (rate.specificity, -rate.id))
    pending = details.option is DeliveryOption.PICKUP and best.terminal is None
    return DeliveryQuote(
        option=details.option, fee=Decimal(best.fee), state=state, city=city,
        university=university, terminal=terminal, support_required=False,
        terminal_pending=pending,
        message=(
            "This terminal is not verified yet; we will confirm it with you."
            if pending else ""
        ),
        rate_id=best.id,
    )


def _unserved_message(option: DeliveryOption, place: str) -> str:
    if option in (DeliveryOption.STANDARD, DeliveryOption.EXPRESS):
        return (
            f"Hand delivery is not available in {place}. "
            "Choose terminal pickup, or contact us to arrange delivery."
        )
    return f"We do not have a rate for {place}. Contact us to arrange delivery."
