"""Delivery pricing rules — pure, run against the storefront's real service area."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.cli.seed_delivery import build_rates, load_data
from app.domains.delivery.domain.entities import (
    DeliveryDetails,
    DeliveryOption,
    DeliveryRate,
)
from app.domains.delivery.domain.rules import normalize_state, quote, same_place
from app.shared.exceptions import ValidationError

STANDARD, EXPRESS, PICKUP, ENQUIRY = (
    DeliveryOption.STANDARD, DeliveryOption.EXPRESS, DeliveryOption.PICKUP, DeliveryOption.ENQUIRY,
)


def _numbered(rates: list[DeliveryRate]) -> list[DeliveryRate]:
    return [
        DeliveryRate(
            id=index, option=r.option, fee=r.fee, state=r.state, city=r.city,
            university=r.university, terminal=r.terminal, is_active=r.is_active,
        )
        for index, r in enumerate(rates, start=1)
    ]


@pytest.fixture(scope="module")
def real_rates() -> list[DeliveryRate]:
    return _numbered(build_rates(load_data()))


def _home(state: str, city: str, option: DeliveryOption = STANDARD) -> DeliveryDetails:
    return DeliveryDetails(option=option, state=state, city=city, address="1 Some Street")


# ── the service area, as the storefront defines it ──────────────────────


@pytest.mark.parametrize(
    ("state", "city", "option", "fee"),
    [
        ("Lagos State", "Ikeja", STANDARD, "2500.00"),
        ("lagos", "Lekki", STANDARD, "2500.00"),
        ("Ogun State", "Abeokuta", STANDARD, "2500.00"),
        ("Lagos State", "Yaba", EXPRESS, "4500.00"),
        ("Ogun", "Ota", EXPRESS, "4500.00"),
        ("Rivers State", "Port Harcourt", STANDARD, "2500.00"),
        ("Rivers", "Old GRA", STANDARD, "2500.00"),
        ("Rivers", "Rumuola", EXPRESS, "4500.00"),
        ("PH", "", STANDARD, "2500.00"),  # a bare PH / Rivers means Port Harcourt
        ("Rivers State", "", STANDARD, "2500.00"),
    ],
)
def test_served_places_are_priced(
    real_rates: list[DeliveryRate], state: str, city: str, option: DeliveryOption, fee: str
) -> None:
    result = quote(_home(state, city, option), real_rates)

    assert result.fee == Decimal(fee)
    assert result.support_required is False
    assert result.is_priced


@pytest.mark.parametrize(
    ("state", "city"),
    [
        ("Rivers State", "Bonny"),  # Rivers, but outside Port Harcourt
        ("Rivers State", "Elele"),  # not Elelenwo: whole words, not substrings
        ("Oyo State", "Ibadan"),
        ("Kano", "Kano"),
        ("Abuja", "Garki"),
        ("Delta", "Warri"),
    ],
)
def test_places_outside_the_service_area_are_never_given_an_invented_price(
    real_rates: list[DeliveryRate], state: str, city: str
) -> None:
    for option in (STANDARD, EXPRESS):
        result = quote(_home(state, city, option), real_rates)
        assert result.fee is None
        assert result.support_required is True
        assert "not available" in result.message


# ── university campuses ─────────────────────────────────────────────────


def test_a_listed_campus_is_priced_and_its_state_is_worked_out(
    real_rates: list[DeliveryRate],
) -> None:
    details = DeliveryDetails(
        option=STANDARD, university="University of Lagos, Akoka (UNILAG)", hostel_room="Moremi 204"
    )

    result = quote(details, real_rates)

    assert result.fee == Decimal("2500.00")
    assert result.state == "Lagos State"  # from the campus, not typed by the shopper
    assert details.is_student is True


def test_a_port_harcourt_campus_is_served_without_a_city(
    real_rates: list[DeliveryRate],
) -> None:
    details = DeliveryDetails(
        option=STANDARD, university="University of Port Harcourt (UNIPORT)", hostel_room="B12"
    )

    result = quote(details, real_rates)

    assert (result.fee, result.state) == (Decimal("2500.00"), "Rivers State")


def test_an_unlisted_campus_outside_the_area_needs_the_shop(
    real_rates: list[DeliveryRate],
) -> None:
    details = DeliveryDetails(
        option=STANDARD, university="Ahmadu Bello University", hostel_room="A1", state="Kaduna"
    )

    assert quote(details, real_rates).support_required is True


# ── terminal pickup ─────────────────────────────────────────────────────


def test_a_verified_terminal_is_free_and_confirmed(real_rates: list[DeliveryRate]) -> None:
    details = DeliveryDetails(
        option=PICKUP, state="Lagos State", terminal="Ojota Terminal (7 Ikorodu Road, Ojota)"
    )

    result = quote(details, real_rates)

    assert result.fee == Decimal("0")
    assert result.terminal_pending is False


def test_an_unlisted_terminal_is_accepted_but_flagged_for_the_shop(
    real_rates: list[DeliveryRate],
) -> None:
    details = DeliveryDetails(option=PICKUP, state="Bauchi", terminal="Bauchi Motor Park")

    result = quote(details, real_rates)

    assert result.fee == Decimal("0")
    assert result.terminal_pending is True
    assert result.is_priced


# ── specificity: the most specific rate wins ────────────────────────────


def _rate(fee: str, **place: str) -> DeliveryRate:
    return DeliveryRate(id=0, option=STANDARD, fee=Decimal(fee), **place)  # type: ignore[arg-type]


def test_the_most_specific_matching_rate_wins() -> None:
    rates = _numbered([
        _rate("1000", state="Lagos State"),
        _rate("1500", state="Lagos State", city="Ikorodu"),
        _rate("800", state="Lagos State", city="Ikorodu", university="LASUSTECH"),
        _rate("100", state="Lagos State", city="Ikorodu", university="LASUSTECH", terminal="T1"),
    ])

    def price(**fields: str) -> Decimal | None:
        return quote(DeliveryDetails(option=STANDARD, address="x", **fields), rates).fee  # type: ignore[arg-type]

    assert price(state="Lagos", city="Yaba") == Decimal("1000")          # state fallback
    assert price(state="Lagos", city="Ikorodu") == Decimal("1500")       # city beats state
    assert price(state="Lagos", city="Ikorodu", university="LASUSTECH",
                 hostel_room="r") == Decimal("800")                      # campus beats city


def test_an_inactive_rate_is_ignored() -> None:
    rates = _numbered([
        DeliveryRate(id=0, option=STANDARD, fee=Decimal("1"), state="Lagos State", is_active=False),
    ])
    assert quote(_home("Lagos", "Yaba"), rates).support_required is True


def test_equal_specificity_is_decided_by_the_older_rate() -> None:
    rates = _numbered([_rate("1000", state="Lagos State"), _rate("2000", state="Lagos State")])
    assert quote(_home("Lagos", "Yaba"), rates).fee == Decimal("1000")


# ── enquiry, forms and helpers ──────────────────────────────────────────


def test_an_enquiry_is_never_priced(real_rates: list[DeliveryRate]) -> None:
    result = quote(DeliveryDetails(option=ENQUIRY, state="Lagos"), real_rates)
    assert (result.fee, result.support_required, result.is_priced) == (None, True, False)


@pytest.mark.parametrize(
    ("details", "needle"),
    [
        (DeliveryDetails(option=STANDARD, state="Lagos", city="Yaba"), "address"),
        (DeliveryDetails(option=STANDARD, address="1 St", state="Lagos"), "city"),
        (DeliveryDetails(option=STANDARD, university="UNILAG"), "hostel"),
        (DeliveryDetails(option=EXPRESS, address="1 St", city="Yaba"), "state"),
        (DeliveryDetails(option=PICKUP, state="Lagos"), "terminal"),
        (DeliveryDetails(option=PICKUP, terminal="Ojota"), "state"),
    ],
)
def test_an_incomplete_form_is_refused_before_it_is_priced(
    details: DeliveryDetails, needle: str
) -> None:
    with pytest.raises(ValidationError, match=needle):
        details.validate()


def test_the_option_can_be_given_as_a_plain_string() -> None:
    details = DeliveryDetails(option="standard", state="Lagos", city="Yaba", address="x")  # type: ignore[arg-type]
    assert details.option is DeliveryOption.STANDARD


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("lagos", "Lagos State"), ("LAGOS STATE", "Lagos State"), ("Ogun", "Ogun State"),
        ("ph", "Rivers State"), ("Port Harcourt", "Rivers State"), ("abuja", "FCT - Abuja"),
        ("FCT", "FCT - Abuja"), ("ibadan", "Oyo State"), ("kano", "Kano State"),
        ("bauchi", "Bauchi"), ("", ""),
    ],
)
def test_state_names_are_normalised(raw: str, expected: str) -> None:
    assert normalize_state(raw) == expected


def test_places_match_by_whole_words() -> None:
    assert same_place("Ikeja", "Ikeja GRA")
    assert same_place("Port Harcourt (City)", "port harcourt")
    assert same_place("Choba", "Choba (Uniport Axis)")
    assert not same_place("Elele", "Elelenwo")
    assert not same_place("Old GRA", "GRA Phase 1, 2 & 3")
    assert not same_place("D", "D-Line")  # too short to mean anything
    assert not same_place("", "Ikeja")


def test_the_seed_covers_the_whole_service_area(real_rates: list[DeliveryRate]) -> None:
    by_option = {o: [r for r in real_rates if r.option is o] for o in DeliveryOption}
    counts = (len(by_option[STANDARD]), len(by_option[EXPRESS]), len(by_option[PICKUP]))
    assert counts == (49, 19, 49)
    assert len({rate.key for rate in real_rates}) == len(real_rates)  # no duplicate rules
