"""Typer application.

Thin on purpose: parse arguments, call a service, render the result. Every command
here should be readable in one screen. The logic being called lives in
:mod:`mizan.services`, which knows nothing about Typer or Rich.

Note the absence of ``from __future__ import annotations``. Typer resolves parameter
types at import time to build the parser, and leaving annotations concrete keeps that
straightforward.
"""

import sqlite3
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import typer
from rich.console import Console

from . import db, render, services
from .importers import read_csv, write_csv
from .money import MoneyError, format_money, parse_money
from .services import MizanError

app = typer.Typer(
    name="mizan",
    help="Track expenses and budgets from the command line.",
    no_args_is_help=True,
    add_completion=True,
)
categories_app = typer.Typer(help="Create, list, and rename categories.", no_args_is_help=True)
budget_app = typer.Typer(help="Set monthly spending limits.", no_args_is_help=True)
db_app = typer.Typer(help="Inspect the database.", no_args_is_help=True)

app.add_typer(categories_app, name="categories")
app.add_typer(budget_app, name="budget")
app.add_typer(db_app, name="db")

console = Console()
error_console = Console(stderr=True)


@contextmanager
def _session(*, require_init: bool = True) -> Iterator[sqlite3.Connection]:
    """Open the database, turn domain errors into a clean exit code 1.

    Every command funnels through here so that error reporting is in one place rather
    than repeated in a dozen except blocks.
    """
    path = db.default_db_path()
    conn = db.connect(path)
    try:
        if require_init and db.current_version(conn) == 0:
            raise MizanError(f"No database at {path}. Run: mizan init")
        yield conn
    except (MizanError, MoneyError) as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc
    finally:
        conn.close()


def _this_month() -> str:
    return date.today().strftime("%Y-%m")


@app.command()
def init() -> None:
    """Create the database and apply any pending migrations."""
    path = db.default_db_path()
    with _session(require_init=False) as conn:
        version = services.initialize(conn)
    console.print(f"Database ready at [bold]{path}[/bold], schema version {version}.")


@app.command()
def add(
    amount: str = typer.Argument(..., help="Amount in dollars, for example 12.50."),
    category: str = typer.Argument(..., help="Category name. It must already exist."),
    note: str | None = typer.Option(None, "--note", "-n", help="Optional description."),
    occurred_on: str | None = typer.Option(
        None, "--date", "-d", help="ISO-8601 date. Defaults to today."
    ),
) -> None:
    """Record an expense."""
    with _session() as conn:
        transaction = services.add_transaction(
            conn,
            amount_cents=parse_money(amount),
            category_name=category,
            occurred_on=occurred_on,
            note=note,
        )
    console.print(
        f"Added [bold]{format_money(transaction.amount_cents)}[/bold]"
        f" to {transaction.category_name} on {transaction.occurred_on}."
    )


@app.command("list")
def list_transactions(
    month: str | None = typer.Option(None, "--month", "-m", help="Filter to a month, as 2026-09."),
    category: str | None = typer.Option(None, "--category", "-c", help="Filter to one category."),
) -> None:
    """List transactions, newest first."""
    with _session() as conn:
        transactions = services.list_transactions(conn, month=month, category_name=category)

    if not transactions:
        console.print("No transactions match that filter.")
        return
    console.print(render.transactions_table(transactions))


@app.command()
def summary(
    month: str | None = typer.Option(
        None, "--month", "-m", help="Month to summarize. Defaults to now."
    ),
) -> None:
    """Show spend against budget for a month."""
    target = month or _this_month()
    with _session() as conn:
        rows = services.summarize(conn, target)

    if not rows:
        console.print(f"Nothing recorded for {target}.")
        return
    console.print(render.summary_table(rows, target))


@app.command()
def undo() -> None:
    """Reverse the most recent command that changed the database."""
    with _session() as conn:
        description = services.undo(conn)
    console.print(f"Undid: [bold]{description}[/bold]")


@app.command()
def export(
    output_format: str = typer.Option(
        "csv", "--format", "-f", help="Output format. Only csv is supported."
    ),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Write here instead of standard output."
    ),
    month: str | None = typer.Option(None, "--month", "-m", help="Filter to a month, as 2026-09."),
    category: str | None = typer.Option(None, "--category", "-c", help="Filter to one category."),
) -> None:
    """Write transactions out as CSV."""
    with _session() as conn:
        if output_format.lower() != "csv":
            raise MizanError(f"Unsupported format {output_format!r}. Only csv is supported.")
        transactions = services.list_transactions(conn, month=month, category_name=category)

        if output is None:
            write_csv(sys.stdout, transactions)
            return

        with output.open("w", encoding="utf-8", newline="") as stream:
            count = write_csv(stream, transactions)
        console.print(f"Wrote {count} transactions to [bold]{output}[/bold].")


@app.command("import")
def import_csv(
    source: Path = typer.Argument(
        ..., exists=True, dir_okay=False, readable=True, help="CSV file to read."
    ),
) -> None:
    """Import transactions from a CSV file.

    The whole file is validated before anything is written, and the import is recorded
    as a single command, so `mizan undo` reverses all of it or none of it.
    """
    with _session() as conn:
        with source.open(encoding="utf-8", newline="") as stream:
            rows = read_csv(stream)
        count = services.import_transactions(conn, rows)
    console.print(f"Imported [bold]{count}[/bold] transactions from {source}.")


@categories_app.command("add")
def categories_add(name: str = typer.Argument(..., help="Name of the new category.")) -> None:
    """Create a category."""
    with _session() as conn:
        category = services.add_category(conn, name)
    console.print(f"Added category [bold]{category.name}[/bold].")


@categories_app.command("list")
def categories_list() -> None:
    """List every category."""
    with _session() as conn:
        categories = services.list_categories(conn)

    if not categories:
        console.print("No categories yet. Add one with: mizan categories add groceries")
        return
    console.print(render.categories_table(categories))


@categories_app.command("rename")
def categories_rename(
    old_name: str = typer.Argument(..., metavar="OLD", help="Current name."),
    new_name: str = typer.Argument(..., metavar="NEW", help="Replacement name."),
) -> None:
    """Rename a category, keeping its transactions attached."""
    with _session() as conn:
        before = services.get_category(conn, old_name).name
        category = services.rename_category(conn, old_name, new_name)
    console.print(f"Renamed [bold]{before}[/bold] to [bold]{category.name}[/bold].")


@budget_app.command("set")
def budget_set(
    category: str = typer.Argument(..., help="Category to limit."),
    amount: str = typer.Argument(..., help="Monthly limit in dollars, for example 400."),
    month: str | None = typer.Option(None, "--month", "-m", help="Month to apply it to."),
) -> None:
    """Set a monthly spending limit for one category."""
    with _session() as conn:
        budget = services.set_budget(
            conn,
            category_name=category,
            limit_cents=parse_money(amount),
            month=month or _this_month(),
        )
    console.print(render.budget_line(budget))


@db_app.command("path")
def db_path() -> None:
    """Print where the database file lives."""
    path = db.default_db_path()
    console.print(str(path), highlight=False, soft_wrap=True)
    if not path.exists():
        error_console.print("[yellow]It does not exist yet. Run: mizan init[/yellow]")


if __name__ == "__main__":  # pragma: no cover
    app()
