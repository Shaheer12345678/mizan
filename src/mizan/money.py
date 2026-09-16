"""Money handling.

Amounts live as integer cents everywhere except the display layer. Parsing goes
str -> Decimal -> int and never touches float, because binary floating point cannot
represent most decimal fractions exactly: summing 0.01 a thousand times as a float
does not produce 10.00. A budget tool that drifts by a cent per transaction is wrong
in the one way users notice.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

__all__ = ["MoneyError", "format_money", "parse_money", "to_decimal_string"]

# Optional sign and currency symbol, digits with optional thousands separators,
# and at most two decimal places.
_AMOUNT = re.compile(r"^(?P<sign>[-+])?\$?(?P<whole>\d{1,3}(?:,\d{3})*|\d+)(?:\.(?P<frac>\d+))?$")

CENTS_PER_UNIT = 100


class MoneyError(ValueError):
    """Raised when a string cannot be read as an exact amount of money."""


def parse_money(text: str) -> int:
    """Parse a dollar amount into integer cents.

    Accepts forms like ``12.50``, ``$12.50``, ``1,234.56``, ``12`` and ``-5.00``.
    Rejects anything with more than two decimal places rather than rounding it,
    since silent rounding is the exact failure integer cents exist to prevent.
    """
    candidate = text.strip()
    if not candidate:
        raise MoneyError("Amount is empty.")

    match = _AMOUNT.match(candidate)
    if match is None:
        raise MoneyError(f"Cannot read {text!r} as an amount. Use a form like 12.50.")

    frac = match.group("frac")
    if frac is not None and len(frac) > 2:
        raise MoneyError(
            f"Amount {text!r} has more than two decimal places. "
            "Money is stored in whole cents, so this would have to be rounded."
        )

    normalized = f"{match.group('sign') or ''}{match.group('whole').replace(',', '')}"
    if frac is not None:
        normalized = f"{normalized}.{frac}"

    try:
        amount = Decimal(normalized)
    except InvalidOperation as exc:  # pragma: no cover - the regex already rejects these
        raise MoneyError(f"Cannot read {text!r} as an amount.") from exc

    return int(amount * CENTS_PER_UNIT)


def format_money(cents: int) -> str:
    """Format integer cents as a dollar string, for example ``1250`` -> ``$12.50``."""
    sign = "-" if cents < 0 else ""
    whole, remainder = divmod(abs(cents), CENTS_PER_UNIT)
    return f"{sign}${whole:,}.{remainder:02d}"


def to_decimal_string(cents: int) -> str:
    """Format integer cents as a bare decimal string, for example ``1250`` -> ``12.50``.

    Used for CSV output, where a currency symbol and thousands separators would only
    have to be stripped back off on the way in.
    """
    sign = "-" if cents < 0 else ""
    whole, remainder = divmod(abs(cents), CENTS_PER_UNIT)
    return f"{sign}{whole}.{remainder:02d}"
