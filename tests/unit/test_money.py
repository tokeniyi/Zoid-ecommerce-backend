from decimal import Decimal

from app.shared.money import serialize_money


def test_serialize_money_preserves_fixed_two_decimal_places() -> None:
    assert serialize_money(Decimal("58500")) == "58500.00"
    assert serialize_money(Decimal("12.5")) == "12.50"


def test_serialize_money_does_not_introduce_float_precision() -> None:
    assert serialize_money(Decimal("0.10") + Decimal("0.20")) == "0.30"
