"""Rich renderables.

Everything here is presentation. It reads dataclasses and returns something Rich can
print, which keeps formatting decisions out of the service layer.

The budget bar is drawn with ASCII rather than block characters so that it renders the
same in a Windows console as it does in a terminal with full Unicode support.
"""

from __future__ import annotations

from collections.abc import Sequence

from rich.table import Table

from .models import Budget, Category, SummaryRow, Transaction
from .money import format_money

__all__ = [
    "BAR_WIDTH",
    "budget_bar",
    "budget_line",
    "categories_table",
    "summary_table",
    "transactions_table",
]

BAR_WIDTH = 20

_OVER_BUDGET_STYLE = "bold red"
_NEAR_BUDGET_STYLE = "yellow"
_UNDER_BUDGET_STYLE = "green"


def budget_bar(fraction: float | None, width: int = BAR_WIDTH) -> str:
    """Draw a proportion as an ASCII bar.

    Anything over the limit still fills the bar rather than overflowing it. The
    percentage next to it is what carries the overspend.
    """
    if fraction is None:
        return " " * width
    filled = min(width, max(0, round(fraction * width)))
    return "#" * filled + "." * (width - filled)


def _usage_style(fraction: float | None) -> str:
    if fraction is None:
        return ""
    if fraction > 1.0:
        return _OVER_BUDGET_STYLE
    if fraction >= 0.9:
        return _NEAR_BUDGET_STYLE
    return _UNDER_BUDGET_STYLE


def transactions_table(transactions: Sequence[Transaction]) -> Table:
    table = Table(title="Transactions", title_justify="left", header_style="bold")
    table.add_column("ID", justify="right", style="dim")
    table.add_column("Date")
    table.add_column("Category")
    table.add_column("Amount", justify="right")
    table.add_column("Note", overflow="fold")

    for transaction in transactions:
        table.add_row(
            str(transaction.id),
            transaction.occurred_on,
            transaction.category_name,
            format_money(transaction.amount_cents),
            transaction.note or "",
        )

    total = sum(transaction.amount_cents for transaction in transactions)
    table.add_section()
    table.add_row("", "", "[bold]Total[/bold]", f"[bold]{format_money(total)}[/bold]", "")
    return table


def categories_table(categories: Sequence[Category]) -> Table:
    table = Table(title="Categories", title_justify="left", header_style="bold")
    table.add_column("ID", justify="right", style="dim")
    table.add_column("Name")

    for category in categories:
        table.add_row(str(category.id), category.name)

    return table


def summary_table(rows: Sequence[SummaryRow], month: str) -> Table:
    table = Table(title=f"Summary for {month}", title_justify="left", header_style="bold")
    table.add_column("Category")
    table.add_column("Spent", justify="right")
    table.add_column("Budget", justify="right")
    table.add_column("Used", justify="right")
    table.add_column("", justify="left")

    for row in rows:
        fraction = row.fraction_used
        style = _usage_style(fraction)
        used = "-" if fraction is None else f"{fraction * 100:.0f}%"
        table.add_row(
            row.category_name,
            format_money(row.spent_cents),
            "-" if row.limit_cents is None else format_money(row.limit_cents),
            f"[{style}]{used}[/{style}]" if style else used,
            budget_bar(fraction),
        )

    total_spent = sum(row.spent_cents for row in rows)
    total_limit = sum(row.limit_cents for row in rows if row.limit_cents is not None)
    table.add_section()
    table.add_row(
        "[bold]Total[/bold]",
        f"[bold]{format_money(total_spent)}[/bold]",
        f"[bold]{format_money(total_limit)}[/bold]" if total_limit else "-",
        "",
        "",
    )
    return table


def budget_line(budget: Budget) -> str:
    """One-line confirmation for a budget that was just set."""
    return (
        f"Budget for {budget.category_name} in {budget.month}"
        f" set to {format_money(budget.limit_cents)}."
    )
