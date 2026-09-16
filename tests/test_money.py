"""Money precision.

The first two tests are the reason this project stores integer cents at all. Everything
else here is guarding the edges of the parser that makes that possible.
"""

from __future__ import annotations

import pytest

from mizan.money import MoneyError, format_money, parse_money, to_decimal_string


def test_sum_of_1000_one_cent_amounts_is_exactly_ten_dollars() -> None:
    """The headline guarantee: a thousand pennies is ten dollars, exactly."""
    total = sum(parse_money("0.01") for _ in range(1000))

    assert total == 1000
    assert format_money(total) == "$10.00"


def test_the_same_total_accumulated_as_float_does_not_reach_ten_dollars() -> None:
    """The failure being avoided, pinned down so the reasoning is not just a claim.

    This accumulates with ``+=`` rather than calling ``sum()``, for two reasons. It is
    how a ledger actually adds a transaction to a running total, and since Python 3.12
    the builtin ``sum()`` applies compensated summation to floats, which would hide the
    very drift this test exists to demonstrate.
    """
    naive = 0.0
    for _ in range(1000):
        naive += 0.01

    assert naive != 10.00
    assert abs(naive - 10.00) > 0


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12.50", 1250),
        ("12.5", 1250),
        ("12", 1200),
        ("0.01", 1),
        ("0", 0),
        ("$12.50", 1250),
        ("1,234.56", 123456),
        ("-5.00", -500),
        ("+5.00", 500),
        ("  7.25  ", 725),
    ],
)
def test_parse_money_reads_accepted_forms(text: str, expected: int) -> None:
    assert parse_money(text) == expected


def test_parse_money_rejects_more_than_two_decimal_places() -> None:
    """Rounding here would silently lose the fraction of a cent. Refuse instead."""
    with pytest.raises(MoneyError, match="two decimal places"):
        parse_money("12.505")


@pytest.mark.parametrize("text", ["", "   ", "abc", "12.5.0", "1,23.45", "$", "12 50", "1e3"])
def test_parse_money_rejects_malformed_input(text: str) -> None:
    with pytest.raises(MoneyError):
        parse_money(text)


@pytest.mark.parametrize(
    ("cents", "expected"),
    [
        (0, "$0.00"),
        (1, "$0.01"),
        (1250, "$12.50"),
        (-1250, "-$12.50"),
        (123456, "$1,234.56"),
        (100000000, "$1,000,000.00"),
    ],
)
def test_format_money_renders_dollars(cents: int, expected: str) -> None:
    assert format_money(cents) == expected


@pytest.mark.parametrize(
    ("cents", "expected"),
    [(0, "0.00"), (5, "0.05"), (1250, "12.50"), (-1250, "-12.50"), (123456, "1234.56")],
)
def test_to_decimal_string_omits_symbol_and_separators(cents: int, expected: str) -> None:
    """CSV output has to round trip, so it carries no currency decoration."""
    assert to_decimal_string(cents) == expected


@pytest.mark.parametrize("cents", [0, 1, 99, 100, 1250, 123456, -1, -123456])
def test_formatting_round_trips_back_to_the_same_cents(cents: int) -> None:
    assert parse_money(format_money(cents)) == cents
    assert parse_money(to_decimal_string(cents)) == cents
