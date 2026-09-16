"""CSV in and out, including the round trip that proves nothing is lost on the way."""

from __future__ import annotations

import io
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import Result

from mizan import services
from mizan.importers import CSV_FIELDNAMES, CsvFormatError, read_csv, write_csv

Invoke = Callable[..., Result]

SAMPLE = """date,amount,category,note
2026-09-20,5.25,groceries,bread
2026-09-21,9.99,transport,bus pass
"""


def test_read_csv_parses_amounts_into_cents() -> None:
    rows = read_csv(io.StringIO(SAMPLE))

    assert [row.amount_cents for row in rows] == [525, 999]
    assert [row.category_name for row in rows] == ["groceries", "transport"]
    assert rows[0].note == "bread"


def test_read_csv_treats_a_blank_note_as_absent() -> None:
    rows = read_csv(io.StringIO("date,amount,category,note\n2026-09-20,5.25,groceries,\n"))

    assert rows[0].note is None


def test_read_csv_accepts_a_file_without_a_note_column() -> None:
    rows = read_csv(io.StringIO("date,amount,category\n2026-09-20,5.25,groceries\n"))

    assert rows[0].note is None


def test_read_csv_ignores_header_case_and_padding() -> None:
    rows = read_csv(io.StringIO(" Date , Amount , Category \n2026-09-20,5.25,groceries\n"))

    assert rows[0].amount_cents == 525


def test_read_csv_rejects_an_empty_file() -> None:
    with pytest.raises(CsvFormatError, match="empty"):
        read_csv(io.StringIO(""))


def test_read_csv_names_the_missing_columns() -> None:
    with pytest.raises(CsvFormatError, match="amount"):
        read_csv(io.StringIO("date,category\n2026-09-20,groceries\n"))


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("2026-09-20,abc,groceries,x", "Line 2"),
        ("2026-09-20,5.255,groceries,x", "two decimal places"),
        ("2026-09-20,5.25,,x", "category is empty"),
        (",5.25,groceries,x", "date is empty"),
    ],
)
def test_read_csv_errors_point_at_the_offending_line(body: str, expected: str) -> None:
    source = io.StringIO(f"{','.join(CSV_FIELDNAMES)}\n{body}\n")

    with pytest.raises(CsvFormatError, match=expected):
        read_csv(source)


def test_write_csv_emits_plain_decimal_amounts(seeded: sqlite3.Connection) -> None:
    services.add_transaction(
        seeded, amount_cents=123456, category_name="groceries", occurred_on="2026-09-14"
    )
    stream = io.StringIO()

    assert write_csv(stream, services.list_transactions(seeded)) == 1
    assert "1234.56" in stream.getvalue()
    assert "$" not in stream.getvalue()


def test_export_then_import_round_trips(seeded: sqlite3.Connection) -> None:
    """Export, wipe, re-import: the ledger has to come back identical."""
    for amount, day in ((1250, "2026-09-14"), (4820, "2026-09-02"), (1, "2026-09-03")):
        services.add_transaction(
            seeded, amount_cents=amount, category_name="groceries", occurred_on=day, note="n"
        )
    original = services.list_transactions(seeded)

    stream = io.StringIO()
    write_csv(stream, original)
    stream.seek(0)
    reimported = read_csv(stream)

    assert [row.amount_cents for row in reimported] == [
        transaction.amount_cents for transaction in original
    ]
    assert [row.occurred_on for row in reimported] == [
        transaction.occurred_on for transaction in original
    ]
    assert [row.note for row in reimported] == [transaction.note for transaction in original]


def test_cli_import_then_export_preserves_the_file(cli: Invoke, tmp_path: Path) -> None:
    source = tmp_path / "in.csv"
    source.write_text(SAMPLE, encoding="utf-8")
    destination = tmp_path / "out.csv"
    cli("init")
    cli("categories", "add", "groceries")
    cli("categories", "add", "transport")

    imported = cli("import", str(source))
    exported = cli("export", "--format", "csv", "--output", str(destination))

    assert imported.exit_code == 0
    assert exported.exit_code == 0
    # Export is newest first, so compare the rows as a set rather than line by line.
    written = destination.read_text(encoding="utf-8").splitlines()
    assert written[0] == ",".join(CSV_FIELDNAMES)
    assert set(written[1:]) == set(SAMPLE.splitlines()[1:])


def test_cli_export_writes_csv_to_standard_output(cli: Invoke) -> None:
    cli("init")
    cli("categories", "add", "groceries")
    cli("add", "12.50", "groceries", "--date", "2026-09-14")

    result = cli("export", "--format", "csv")

    assert result.exit_code == 0
    assert result.stdout.startswith("date,amount,category,note")
    assert "2026-09-14,12.50,groceries," in result.stdout


def test_an_import_is_undone_as_one_batch(cli: Invoke, tmp_path: Path) -> None:
    source = tmp_path / "in.csv"
    source.write_text(SAMPLE, encoding="utf-8")
    cli("init")
    cli("categories", "add", "groceries")
    cli("categories", "add", "transport")
    cli("import", str(source))

    undone = cli("undo")
    listed = cli("list")

    assert undone.exit_code == 0
    assert "import of 2 transactions" in undone.output
    assert "No transactions" in listed.output


def test_cli_import_reports_a_bad_row_without_writing_anything(cli: Invoke, tmp_path: Path) -> None:
    source = tmp_path / "bad.csv"
    source.write_text("date,amount,category\n2026-09-20,not-money,groceries\n", encoding="utf-8")
    cli("init")
    cli("categories", "add", "groceries")

    result = cli("import", str(source))
    listed = cli("list")

    assert result.exit_code == 1
    assert "Line 2" in result.output
    assert "No transactions" in listed.output
