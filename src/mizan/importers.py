"""CSV import and export.

The on-disk format is deliberately boring: a header row, one transaction per line,
amounts as plain decimal strings. It is the format a spreadsheet exports by default,
because the people most likely to import anything are coming from a spreadsheet.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from typing import TextIO

from .models import NewTransaction, Transaction
from .money import MoneyError, parse_money, to_decimal_string
from .services import MizanError

__all__ = ["CSV_FIELDNAMES", "CsvFormatError", "read_csv", "write_csv"]

CSV_FIELDNAMES = ("date", "amount", "category", "note")


class CsvFormatError(MizanError):
    """A CSV file could not be read as transactions."""


def read_csv(stream: TextIO) -> list[NewTransaction]:
    """Parse transactions out of a CSV stream.

    Nothing is written to the database here, so a file that fails validation half way
    through leaves no partial import behind. Errors name the line they came from,
    because "invalid amount" on a 400 row export is not an actionable message.
    """
    reader = csv.DictReader(stream)

    if reader.fieldnames is None:
        raise CsvFormatError("The file is empty. Expected a header row.")

    headers = {(name or "").strip().lower() for name in reader.fieldnames}
    missing = [field for field in CSV_FIELDNAMES if field != "note" and field not in headers]
    if missing:
        raise CsvFormatError(
            f"Missing required column(s): {', '.join(missing)}."
            f" Expected a header row of: {', '.join(CSV_FIELDNAMES)}"
        )

    rows = []
    for raw in reader:
        line = reader.line_num
        record = {(key or "").strip().lower(): (value or "") for key, value in raw.items()}

        category = record.get("category", "").strip()
        if not category:
            raise CsvFormatError(f"Line {line}: category is empty.")

        occurred_on = record.get("date", "").strip()
        if not occurred_on:
            raise CsvFormatError(f"Line {line}: date is empty.")

        try:
            amount_cents = parse_money(record.get("amount", ""))
        except MoneyError as exc:
            raise CsvFormatError(f"Line {line}: {exc}") from exc

        note = record.get("note", "").strip() or None
        rows.append(
            NewTransaction(
                amount_cents=amount_cents,
                category_name=category,
                occurred_on=occurred_on,
                note=note,
            )
        )

    return rows


def write_csv(stream: TextIO, transactions: Iterable[Transaction]) -> int:
    """Write transactions as CSV and return how many were written."""
    writer = csv.DictWriter(stream, fieldnames=list(CSV_FIELDNAMES), lineterminator="\n")
    writer.writeheader()

    count = 0
    for transaction in transactions:
        writer.writerow(
            {
                "date": transaction.occurred_on,
                "amount": to_decimal_string(transaction.amount_cents),
                "category": transaction.category_name,
                "note": transaction.note or "",
            }
        )
        count += 1

    return count
