"""Service layer, exercised without going near the CLI."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from mizan import services
from mizan.models import NewTransaction


def test_services_module_has_no_cli_imports() -> None:
    """The separation the architecture rests on, checked rather than assumed."""
    source = Path(services.__file__).read_text(encoding="utf-8")

    for banned in ("import typer", "from typer", "import rich", "from rich"):
        assert banned not in source, banned


def test_importing_services_does_not_pull_in_typer_or_rich() -> None:
    """Stronger than reading the source: nothing it imports drags them in either."""
    check = (
        "import sys, mizan.services;"
        " assert 'typer' not in sys.modules, 'typer leaked';"
        " assert 'rich' not in sys.modules, 'rich leaked'"
    )
    subprocess.run([sys.executable, "-c", check], check=True)


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


def test_add_category_then_list_it(conn: sqlite3.Connection) -> None:
    created = services.add_category(conn, "groceries")

    assert created.name == "groceries"
    assert [category.name for category in services.list_categories(conn)] == ["groceries"]


def test_category_names_collide_case_insensitively(conn: sqlite3.Connection) -> None:
    services.add_category(conn, "Groceries")

    with pytest.raises(services.DuplicateCategoryError):
        services.add_category(conn, "groceries")


def test_category_names_are_whitespace_normalized(conn: sqlite3.Connection) -> None:
    created = services.add_category(conn, "  eating   out  ")

    assert created.name == "eating out"


def test_empty_category_name_is_rejected(conn: sqlite3.Connection) -> None:
    with pytest.raises(services.ValidationError):
        services.add_category(conn, "   ")


def test_get_category_is_case_insensitive(seeded: sqlite3.Connection) -> None:
    assert services.get_category(seeded, "GROCERIES").name == "groceries"


def test_unknown_category_names_the_command_that_fixes_it(conn: sqlite3.Connection) -> None:
    with pytest.raises(services.CategoryNotFoundError, match="mizan categories add"):
        services.get_category(conn, "nope")


def test_rename_category_keeps_transactions_attached(seeded: sqlite3.Connection) -> None:
    services.add_transaction(seeded, amount_cents=1250, category_name="groceries")

    services.rename_category(seeded, "groceries", "food")

    transactions = services.list_transactions(seeded)
    assert [transaction.category_name for transaction in transactions] == ["food"]


def test_rename_onto_an_existing_name_is_rejected(seeded: sqlite3.Connection) -> None:
    with pytest.raises(services.DuplicateCategoryError):
        services.rename_category(seeded, "groceries", "transport")


def test_rename_can_change_only_capitalisation(seeded: sqlite3.Connection) -> None:
    """A rename onto itself is not a collision with itself."""
    renamed = services.rename_category(seeded, "groceries", "Groceries")

    assert renamed.name == "Groceries"


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


def test_add_transaction_stores_cents_and_defaults_the_date(seeded: sqlite3.Connection) -> None:
    transaction = services.add_transaction(
        seeded, amount_cents=1250, category_name="groceries", note="milk"
    )

    assert transaction.amount_cents == 1250
    assert transaction.note == "milk"
    assert len(transaction.occurred_on) == len("2026-09-14")


def test_add_transaction_rejects_a_non_positive_amount(seeded: sqlite3.Connection) -> None:
    with pytest.raises(services.ValidationError, match="greater than zero"):
        services.add_transaction(seeded, amount_cents=0, category_name="groceries")


def test_add_transaction_rejects_an_unparseable_date(seeded: sqlite3.Connection) -> None:
    with pytest.raises(services.ValidationError, match="not a date"):
        services.add_transaction(
            seeded, amount_cents=100, category_name="groceries", occurred_on="14/09/2026"
        )


def test_add_transaction_rejects_an_unknown_category(conn: sqlite3.Connection) -> None:
    with pytest.raises(services.CategoryNotFoundError):
        services.add_transaction(conn, amount_cents=100, category_name="ghost")


def test_list_transactions_filters_by_month_and_category(seeded: sqlite3.Connection) -> None:
    services.add_transaction(
        seeded, amount_cents=1250, category_name="groceries", occurred_on="2026-09-14"
    )
    services.add_transaction(
        seeded, amount_cents=3000, category_name="transport", occurred_on="2026-09-08"
    )
    services.add_transaction(
        seeded, amount_cents=999, category_name="groceries", occurred_on="2026-08-30"
    )

    assert len(services.list_transactions(seeded)) == 3
    assert len(services.list_transactions(seeded, month="2026-09")) == 2
    assert len(services.list_transactions(seeded, category_name="groceries")) == 2
    assert len(services.list_transactions(seeded, month="2026-09", category_name="groceries")) == 1


def test_list_transactions_rejects_a_malformed_month(seeded: sqlite3.Connection) -> None:
    with pytest.raises(services.ValidationError, match="not a month"):
        services.list_transactions(seeded, month="September")


def test_list_transactions_is_newest_first(seeded: sqlite3.Connection) -> None:
    for day in ("2026-09-02", "2026-09-20", "2026-09-11"):
        services.add_transaction(
            seeded, amount_cents=100, category_name="groceries", occurred_on=day
        )

    dates = [transaction.occurred_on for transaction in services.list_transactions(seeded)]
    assert dates == ["2026-09-20", "2026-09-11", "2026-09-02"]


# ---------------------------------------------------------------------------
# Budgets and summary
# ---------------------------------------------------------------------------


def test_set_budget_replaces_an_earlier_limit(seeded: sqlite3.Connection) -> None:
    services.set_budget(seeded, category_name="groceries", limit_cents=40000, month="2026-09")
    services.set_budget(seeded, category_name="groceries", limit_cents=45000, month="2026-09")

    rows = services.summarize(seeded, "2026-09")
    assert [row.limit_cents for row in rows] == [45000]


def test_set_budget_rejects_a_non_positive_limit(seeded: sqlite3.Connection) -> None:
    with pytest.raises(services.ValidationError, match="greater than zero"):
        services.set_budget(seeded, category_name="groceries", limit_cents=-1, month="2026-09")


def test_summary_reports_spend_against_limit(seeded: sqlite3.Connection) -> None:
    services.set_budget(seeded, category_name="groceries", limit_cents=10000, month="2026-09")
    services.add_transaction(
        seeded, amount_cents=1250, category_name="groceries", occurred_on="2026-09-14"
    )
    services.add_transaction(
        seeded, amount_cents=1250, category_name="groceries", occurred_on="2026-09-15"
    )

    (row,) = services.summarize(seeded, "2026-09")
    assert row.spent_cents == 2500
    assert row.limit_cents == 10000
    assert row.remaining_cents == 7500
    assert row.fraction_used == pytest.approx(0.25)


def test_summary_skips_categories_with_no_spend_and_no_budget(
    seeded: sqlite3.Connection,
) -> None:
    services.add_transaction(
        seeded, amount_cents=1250, category_name="groceries", occurred_on="2026-09-14"
    )

    assert [row.category_name for row in services.summarize(seeded, "2026-09")] == ["groceries"]


def test_summary_ignores_other_months(seeded: sqlite3.Connection) -> None:
    services.add_transaction(
        seeded, amount_cents=1250, category_name="groceries", occurred_on="2026-08-14"
    )

    assert services.summarize(seeded, "2026-09") == []


def test_summary_row_without_a_budget_has_no_fraction(seeded: sqlite3.Connection) -> None:
    services.add_transaction(
        seeded, amount_cents=1250, category_name="groceries", occurred_on="2026-09-14"
    )

    (row,) = services.summarize(seeded, "2026-09")
    assert row.limit_cents is None
    assert row.fraction_used is None
    assert row.remaining_cents is None


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------


def test_undo_on_an_untouched_database_reports_nothing_to_undo(
    conn: sqlite3.Connection,
) -> None:
    with pytest.raises(services.NothingToUndoError):
        services.undo(conn)


def test_undo_reverses_an_add(seeded: sqlite3.Connection) -> None:
    services.add_transaction(seeded, amount_cents=1250, category_name="groceries")

    services.undo(seeded)

    assert services.list_transactions(seeded) == []


def test_undo_soft_deletes_rather_than_dropping_the_row(seeded: sqlite3.Connection) -> None:
    """The row stays for the audit trail. Only the queries filter it out."""
    services.add_transaction(seeded, amount_cents=1250, category_name="groceries")

    services.undo(seeded)

    row = seeded.execute("SELECT deleted_at FROM transactions").fetchone()
    assert row["deleted_at"] is not None


def test_undo_reverses_a_category_add(conn: sqlite3.Connection) -> None:
    services.add_category(conn, "groceries")

    services.undo(conn)

    assert services.list_categories(conn) == []


def test_undo_reverses_a_category_rename(seeded: sqlite3.Connection) -> None:
    services.rename_category(seeded, "groceries", "food")

    services.undo(seeded)

    assert services.get_category(seeded, "groceries").name == "groceries"


def test_undo_removes_a_budget_that_had_no_earlier_value(seeded: sqlite3.Connection) -> None:
    services.set_budget(seeded, category_name="groceries", limit_cents=40000, month="2026-09")

    services.undo(seeded)

    assert services.summarize(seeded, "2026-09") == []


def test_undo_restores_the_previous_budget_limit(seeded: sqlite3.Connection) -> None:
    services.set_budget(seeded, category_name="groceries", limit_cents=40000, month="2026-09")
    services.set_budget(seeded, category_name="groceries", limit_cents=45000, month="2026-09")

    services.undo(seeded)

    (row,) = services.summarize(seeded, "2026-09")
    assert row.limit_cents == 40000


def test_undo_describes_what_it_reversed(seeded: sqlite3.Connection) -> None:
    services.add_transaction(
        seeded, amount_cents=1250, category_name="groceries", occurred_on="2026-09-14"
    )

    assert services.undo(seeded) == "add $12.50 groceries on 2026-09-14"


def test_undo_is_single_level(seeded: sqlite3.Connection) -> None:
    """One step back, by design. A second undo does not walk further into history."""
    services.add_transaction(seeded, amount_cents=1250, category_name="groceries")
    services.add_transaction(seeded, amount_cents=999, category_name="groceries")
    services.undo(seeded)

    with pytest.raises(services.NothingToUndoError, match="already been reversed"):
        services.undo(seeded)

    assert len(services.list_transactions(seeded)) == 1


def test_a_failed_command_leaves_no_journal_entry(seeded: sqlite3.Connection) -> None:
    """Validation happens before the transaction opens, so nothing half-applies."""
    before = services.last_journal_entry(seeded)

    with pytest.raises(services.CategoryNotFoundError):
        services.add_transaction(seeded, amount_cents=100, category_name="ghost")

    after = services.last_journal_entry(seeded)
    assert before is not None
    assert after is not None
    assert after.id == before.id


# ---------------------------------------------------------------------------
# Bulk insert
# ---------------------------------------------------------------------------


def test_import_transactions_stores_a_batch(seeded: sqlite3.Connection) -> None:
    rows = [
        NewTransaction(amount_cents=525, category_name="groceries", occurred_on="2026-09-20"),
        NewTransaction(amount_cents=999, category_name="transport", occurred_on="2026-09-21"),
    ]

    assert services.import_transactions(seeded, rows) == 2
    assert len(services.list_transactions(seeded)) == 2


def test_importing_nothing_is_not_an_error(seeded: sqlite3.Connection) -> None:
    assert services.import_transactions(seeded, []) == 0


def test_a_bad_row_aborts_the_whole_import(seeded: sqlite3.Connection) -> None:
    """Resolved before anything is written, so a bad row leaves no partial ledger."""
    rows = [
        NewTransaction(amount_cents=525, category_name="groceries", occurred_on="2026-09-20"),
        NewTransaction(amount_cents=999, category_name="ghost", occurred_on="2026-09-21"),
    ]

    with pytest.raises(services.CategoryNotFoundError):
        services.import_transactions(seeded, rows)

    assert services.list_transactions(seeded) == []
