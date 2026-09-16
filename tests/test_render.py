"""The presentation layer.

The bar is drawn with ASCII so that it looks the same in a plain Windows console as it
does anywhere else, which also makes it something a test can assert on directly.
"""

from __future__ import annotations

import sqlite3

import pytest
from rich.console import Console

from mizan import render, services


def _plain(renderable: object) -> str:
    """Render to a string with styling and colour stripped."""
    console = Console(width=120, no_color=True, legacy_windows=False)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


@pytest.mark.parametrize(
    ("fraction", "expected"),
    [
        (0.0, "." * 20),
        (0.25, "#" * 5 + "." * 15),
        (0.5, "#" * 10 + "." * 10),
        (1.0, "#" * 20),
        (1.5, "#" * 20),
        (-1.0, "." * 20),
    ],
)
def test_budget_bar_fills_in_proportion(fraction: float, expected: str) -> None:
    assert render.budget_bar(fraction) == expected


def test_budget_bar_is_blank_when_no_budget_is_set() -> None:
    assert render.budget_bar(None).strip() == ""


def test_budget_bar_honours_a_custom_width() -> None:
    assert render.budget_bar(0.5, width=10) == "#####....."


def test_transactions_table_shows_a_total(seeded: sqlite3.Connection) -> None:
    services.add_transaction(
        seeded, amount_cents=1250, category_name="groceries", occurred_on="2026-09-14"
    )
    services.add_transaction(
        seeded, amount_cents=4820, category_name="groceries", occurred_on="2026-09-02"
    )

    output = _plain(render.transactions_table(services.list_transactions(seeded)))

    assert "$12.50" in output
    assert "$48.20" in output
    assert "$60.70" in output


def test_summary_table_reports_percentage_used(seeded: sqlite3.Connection) -> None:
    services.set_budget(seeded, category_name="groceries", limit_cents=10000, month="2026-09")
    services.add_transaction(
        seeded, amount_cents=2500, category_name="groceries", occurred_on="2026-09-14"
    )

    output = _plain(render.summary_table(services.summarize(seeded, "2026-09"), "2026-09"))

    assert "Summary for 2026-09" in output
    assert "25%" in output
    assert "#####" in output


def test_summary_table_marks_a_category_with_no_budget(seeded: sqlite3.Connection) -> None:
    services.add_transaction(
        seeded, amount_cents=2500, category_name="groceries", occurred_on="2026-09-14"
    )

    output = _plain(render.summary_table(services.summarize(seeded, "2026-09"), "2026-09"))

    assert "$25.00" in output
    assert "-" in output


def test_categories_table_lists_names(seeded: sqlite3.Connection) -> None:
    output = _plain(render.categories_table(services.list_categories(seeded)))

    assert "groceries" in output
    assert "transport" in output


def test_budget_line_states_category_month_and_limit(seeded: sqlite3.Connection) -> None:
    budget = services.set_budget(
        seeded, category_name="groceries", limit_cents=40000, month="2026-09"
    )

    assert render.budget_line(budget) == "Budget for groceries in 2026-09 set to $400.00."
