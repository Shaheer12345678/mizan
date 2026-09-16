"""End to end through the Typer app, using the real database file."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from typer.testing import Result

Invoke = Callable[..., Result]


def test_help_lists_every_command(cli: Invoke) -> None:
    result = cli("--help")

    assert result.exit_code == 0
    for command in ("init", "add", "list", "summary", "budget", "categories", "undo", "db"):
        assert command in result.output


def test_init_creates_the_database_file(cli: Invoke, db_path: Path) -> None:
    result = cli("init")

    assert result.exit_code == 0
    assert db_path.exists()
    assert "schema version 2" in result.output


def test_commands_refuse_to_run_before_init(cli: Invoke) -> None:
    result = cli("categories", "list")

    assert result.exit_code == 1
    assert "mizan init" in result.output


def test_add_and_list_a_transaction(cli: Invoke) -> None:
    cli("init")
    cli("categories", "add", "groceries")

    added = cli("add", "12.50", "groceries", "--note", "milk", "--date", "2026-09-14")
    listed = cli("list", "--month", "2026-09")

    assert added.exit_code == 0
    assert "$12.50" in added.output
    assert listed.exit_code == 0
    assert "groceries" in listed.output
    assert "milk" in listed.output


def test_add_rejects_a_fractional_cent(cli: Invoke) -> None:
    cli("init")
    cli("categories", "add", "groceries")

    result = cli("add", "12.505", "groceries")

    assert result.exit_code == 1
    assert "two decimal places" in result.output


def test_add_to_an_unknown_category_exits_one(cli: Invoke) -> None:
    cli("init")

    result = cli("add", "12.50", "ghost")

    assert result.exit_code == 1
    assert "ghost" in result.output


def test_list_with_no_matches_says_so(cli: Invoke) -> None:
    cli("init")

    result = cli("list", "--month", "2026-01")

    assert result.exit_code == 0
    assert "No transactions" in result.output


def test_budget_set_then_summary_shows_the_bar(cli: Invoke) -> None:
    cli("init")
    cli("categories", "add", "groceries")
    cli("add", "60.00", "groceries", "--date", "2026-09-14")

    budget = cli("budget", "set", "groceries", "400", "--month", "2026-09")
    summary = cli("summary", "--month", "2026-09")

    assert budget.exit_code == 0
    assert "$400.00" in budget.output
    assert summary.exit_code == 0
    assert "$60.00" in summary.output
    assert "15%" in summary.output
    assert "#" in summary.output


def test_summary_with_nothing_recorded_says_so(cli: Invoke) -> None:
    cli("init")

    result = cli("summary", "--month", "2026-01")

    assert result.exit_code == 0
    assert "Nothing recorded" in result.output


def test_categories_add_list_and_rename(cli: Invoke) -> None:
    cli("init")
    cli("categories", "add", "groceries")

    renamed = cli("categories", "rename", "groceries", "food")
    listed = cli("categories", "list")

    assert renamed.exit_code == 0
    assert listed.exit_code == 0
    assert "food" in listed.output
    assert "groceries" not in listed.output


def test_categories_list_when_empty_suggests_adding_one(cli: Invoke) -> None:
    cli("init")

    result = cli("categories", "list")

    assert result.exit_code == 0
    assert "No categories yet" in result.output


def test_duplicate_category_exits_one(cli: Invoke) -> None:
    cli("init")
    cli("categories", "add", "groceries")

    result = cli("categories", "add", "Groceries")

    assert result.exit_code == 1
    assert "already exists" in result.output


def test_undo_reverses_the_last_command(cli: Invoke) -> None:
    cli("init")
    cli("categories", "add", "groceries")
    cli("add", "12.50", "groceries", "--date", "2026-09-14")

    undone = cli("undo")
    listed = cli("list")

    assert undone.exit_code == 0
    assert "Undid" in undone.output
    assert "No transactions" in listed.output


def test_undo_with_nothing_to_reverse_exits_one(cli: Invoke) -> None:
    cli("init")

    result = cli("undo")

    assert result.exit_code == 1
    assert "Nothing to undo" in result.output


def test_db_path_prints_the_configured_location(cli: Invoke, db_path: Path) -> None:
    result = cli("db", "path")

    assert result.exit_code == 0
    assert db_path.name in result.output


def test_export_rejects_an_unsupported_format(cli: Invoke) -> None:
    cli("init")

    result = cli("export", "--format", "json")

    assert result.exit_code == 1
    assert "Only csv is supported" in result.output


def test_import_of_a_missing_file_is_rejected_by_the_parser(cli: Invoke, tmp_path: Path) -> None:
    cli("init")

    result = cli("import", str(tmp_path / "absent.csv"))

    assert result.exit_code != 0
