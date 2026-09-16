"""Plain data carried between the service layer and whatever is rendering it.

Frozen dataclasses rather than raw sqlite3.Row objects: the row factory is a database
detail, and pinning it here would leak sqlite3 into every caller.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "Budget",
    "Category",
    "JournalEntry",
    "NewTransaction",
    "SummaryRow",
    "Transaction",
]


@dataclass(frozen=True)
class Category:
    id: int
    name: str


@dataclass(frozen=True)
class Transaction:
    id: int
    amount_cents: int
    category_id: int
    category_name: str
    occurred_on: str
    note: str | None
    created_at: str


@dataclass(frozen=True)
class NewTransaction:
    """A transaction that has been validated but not yet stored."""

    amount_cents: int
    category_name: str
    occurred_on: str
    note: str | None = None


@dataclass(frozen=True)
class Budget:
    category_id: int
    category_name: str
    month: str
    limit_cents: int


@dataclass(frozen=True)
class SummaryRow:
    """One category's standing for a month."""

    category_name: str
    spent_cents: int
    limit_cents: int | None

    @property
    def remaining_cents(self) -> int | None:
        if self.limit_cents is None:
            return None
        return self.limit_cents - self.spent_cents

    @property
    def fraction_used(self) -> float | None:
        """Share of the budget spent, or None when no budget is set.

        This is presentation only. It never feeds back into a stored amount, so the
        float is safe here in a way it would not be on the money path itself.
        """
        if self.limit_cents is None or self.limit_cents == 0:
            return None
        return self.spent_cents / self.limit_cents


@dataclass(frozen=True)
class JournalEntry:
    id: int
    command: str
    payload: str
    created_at: str
    undone_at: str | None
