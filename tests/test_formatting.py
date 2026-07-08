# tests/test_formatting.py
from app.formatting import format_money


def test_plain_amount_has_symbol_and_thousands():
    assert format_money(48000) == "₱48,000.00"


def test_two_decimals():
    assert format_money(1234.5) == "₱1,234.50"


def test_signed_positive():
    assert format_money(48000, signed=True) == "+₱48,000.00"


def test_signed_negative_uses_absolute_value():
    assert format_money(-150, signed=True) == "-₱150.00"


def test_unsigned_negative_keeps_minus_before_symbol():
    assert format_money(-150) == "-₱150.00"
