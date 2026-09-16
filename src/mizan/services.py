"""Business logic.

This module deliberately imports neither Typer nor Rich. Everything here takes a
connection and plain values and returns dataclasses, which is what lets the test
suite exercise the real logic without going through a CLI runner, and what would let
a different frontend reuse it unchanged.

Amounts crossing this boundary are always integer cents.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime, timezone

from .db import migrate
from .models import Budget, Category, JournalEntry, NewTransaction, SummaryRow, Transaction
from .money import format_money

__all__ = [
    "CategoryNotFoundError",
    "DuplicateCategoryError",
    "MizanError",
    "NothingToUndoError",
    "ValidationError",
    "add_category",
    "add_transaction",
    "get_category",
    "import_transactions",
    "initialize",
    "last_journal_entry",
    "list_categories",
    "list_transactions",
    "rename_category",
    "set_budget",
    "summarize",
    "undo",
    "validate_date",
    "validate_month",
]


class MizanError(Exception):
    """Base class for every error a user can cause."""


class ValidationError(MizanError):
    """Input was well formed but not acceptable."""


class CategoryNotFoundError(MizanError):
    """No category by that name."""


class DuplicateCategoryError(MizanError):
    """A category by that name already exists."""


class NothingToUndoError(MizanError):
    """No command is available to reverse."""


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def initialize(conn: sqlite3.Connection) -> int:
    """Bring the database up to the current schema version."""
    return migrate(conn)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_month(text: str) -> str:
    """Check a 'YYYY-MM' month and return it normalized."""
    candidate = text.strip()
    try:
        parsed = datetime.strptime(candidate, "%Y-%m")
    except ValueError:
        raise ValidationError(f"{text!r} is not a month. Use the form 2026-09.") from None
    return parsed.strftime("%Y-%m")


def validate_date(text: str) -> str:
    """Check an ISO-8601 date and return it normalized."""
    candidate = text.strip()
    try:
        parsed = date.fromisoformat(candidate)
    except ValueError:
        raise ValidationError(f"{text!r} is not a date. Use the form 2026-09-14.") from None
    return parsed.isoformat()


def _require_positive(amount_cents: int, *, subject: str) -> int:
    if amount_cents <= 0:
        raise ValidationError(f"{subject} must be greater than zero.")
    return amount_cents


def _clean_category_name(name: str) -> str:
    candidate = " ".join(name.split())
    if not candidate:
        raise ValidationError("Category name is empty.")
    return candidate


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


def get_category(conn: sqlite3.Connection, name: str) -> Category:
    """Look up a category by name, case insensitively."""
    wanted = name.strip()
    row = conn.execute(
        "SELECT id, name FROM categories WHERE name = ? COLLATE NOCASE", (wanted,)
    ).fetchone()
    if row is None:
        raise CategoryNotFoundError(
            f"No category named {wanted!r}. Add it with: mizan categories add {wanted}"
        )
    return Category(id=row["id"], name=row["name"])


def list_categories(conn: sqlite3.Connection) -> list[Category]:
    rows = conn.execute("SELECT id, name FROM categories ORDER BY name COLLATE NOCASE").fetchall()
    return [Category(id=row["id"], name=row["name"]) for row in rows]


def add_category(conn: sqlite3.Connection, name: str) -> Category:
    clean = _clean_category_name(name)
    if _category_exists(conn, clean):
        raise DuplicateCategoryError(f"A category named {clean!r} already exists.")

    with _transaction(conn):
        cursor = conn.execute("INSERT INTO categories (name) VALUES (?)", (clean,))
        category_id = int(cursor.lastrowid or 0)
        _record(
            conn,
            "category_add",
            {"category_id": category_id, "description": f"categories add {clean}"},
        )

    return Category(id=category_id, name=clean)


def rename_category(conn: sqlite3.Connection, old_name: str, new_name: str) -> Category:
    category = get_category(conn, old_name)
    clean = _clean_category_name(new_name)

    # Changing only the capitalisation is a rename onto itself, which is allowed.
    if clean.casefold() != category.name.casefold() and _category_exists(conn, clean):
        raise DuplicateCategoryError(f"A category named {clean!r} already exists.")

    with _transaction(conn):
        conn.execute("UPDATE categories SET name = ? WHERE id = ?", (clean, category.id))
        _record(
            conn,
            "category_rename",
            {
                "category_id": category.id,
                "previous_name": category.name,
                "description": f"categories rename {category.name} to {clean}",
            },
        )

    return Category(id=category.id, name=clean)


def _category_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("SELECT 1 FROM categories WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


def add_transaction(
    conn: sqlite3.Connection,
    *,
    amount_cents: int,
    category_name: str,
    occurred_on: str | None = None,
    note: str | None = None,
) -> Transaction:
    """Record one expense."""
    _require_positive(amount_cents, subject="Amount")
    category = get_category(conn, category_name)
    when = validate_date(occurred_on) if occurred_on else date.today().isoformat()
    created_at = _now()

    with _transaction(conn):
        transaction_id = _insert_transaction(
            conn,
            amount_cents=amount_cents,
            category_id=category.id,
            occurred_on=when,
            note=note,
            created_at=created_at,
        )
        _record(
            conn,
            "add",
            {
                "transaction_ids": [transaction_id],
                "description": f"add {format_money(amount_cents)} {category.name} on {when}",
            },
        )

    return Transaction(
        id=transaction_id,
        amount_cents=amount_cents,
        category_id=category.id,
        category_name=category.name,
        occurred_on=when,
        note=note,
        created_at=created_at,
    )


def list_transactions(
    conn: sqlite3.Connection,
    *,
    month: str | None = None,
    category_name: str | None = None,
) -> list[Transaction]:
    """Transactions, newest first, excluding anything undone."""
    sql = [
        "SELECT t.id, t.amount_cents, t.category_id, c.name AS category_name,",
        "       t.occurred_on, t.note, t.created_at",
        "FROM transactions t",
        "JOIN categories c ON c.id = t.category_id",
        "WHERE t.deleted_at IS NULL",
    ]
    params: list[object] = []

    if month is not None:
        sql.append("AND substr(t.occurred_on, 1, 7) = ?")
        params.append(validate_month(month))

    if category_name is not None:
        # Resolved first so an unknown category is an error rather than an empty table.
        sql.append("AND t.category_id = ?")
        params.append(get_category(conn, category_name).id)

    sql.append("ORDER BY t.occurred_on DESC, t.id DESC")
    rows = conn.execute("\n".join(sql), params).fetchall()

    return [
        Transaction(
            id=row["id"],
            amount_cents=row["amount_cents"],
            category_id=row["category_id"],
            category_name=row["category_name"],
            occurred_on=row["occurred_on"],
            note=row["note"],
            created_at=row["created_at"],
        )
        for row in rows
    ]


def import_transactions(conn: sqlite3.Connection, rows: Sequence[NewTransaction]) -> int:
    """Store a batch of validated transactions and return how many landed.

    The whole batch is one journal entry, so undoing an import removes all of it
    rather than leaving a partial ledger behind.
    """
    if not rows:
        return 0

    resolved = [
        (
            _require_positive(row.amount_cents, subject="Amount"),
            get_category(conn, row.category_name).id,
            validate_date(row.occurred_on),
            row.note,
        )
        for row in rows
    ]
    created_at = _now()

    with _transaction(conn):
        transaction_ids = [
            _insert_transaction(
                conn,
                amount_cents=amount_cents,
                category_id=category_id,
                occurred_on=occurred_on,
                note=note,
                created_at=created_at,
            )
            for amount_cents, category_id, occurred_on, note in resolved
        ]
        _record(
            conn,
            "import",
            {
                "transaction_ids": transaction_ids,
                "description": f"import of {len(transaction_ids)} transactions",
            },
        )

    return len(transaction_ids)


def _insert_transaction(
    conn: sqlite3.Connection,
    *,
    amount_cents: int,
    category_id: int,
    occurred_on: str,
    note: str | None,
    created_at: str,
) -> int:
    cursor = conn.execute(
        "INSERT INTO transactions"
        " (amount_cents, category_id, occurred_on, note, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (amount_cents, category_id, occurred_on, note, created_at),
    )
    return int(cursor.lastrowid or 0)


# ---------------------------------------------------------------------------
# Budgets and summary
# ---------------------------------------------------------------------------


def set_budget(
    conn: sqlite3.Connection,
    *,
    category_name: str,
    limit_cents: int,
    month: str,
) -> Budget:
    """Set or replace one category's limit for a month."""
    _require_positive(limit_cents, subject="Budget limit")
    category = get_category(conn, category_name)
    normalized_month = validate_month(month)

    row = conn.execute(
        "SELECT limit_cents FROM budgets WHERE category_id = ? AND month = ?",
        (category.id, normalized_month),
    ).fetchone()
    previous = int(row["limit_cents"]) if row is not None else None

    with _transaction(conn):
        conn.execute(
            "INSERT INTO budgets (category_id, month, limit_cents) VALUES (?, ?, ?)"
            " ON CONFLICT (category_id, month) DO UPDATE SET limit_cents = excluded.limit_cents",
            (category.id, normalized_month, limit_cents),
        )
        _record(
            conn,
            "budget_set",
            {
                "category_id": category.id,
                "month": normalized_month,
                "previous_limit_cents": previous,
                "description": (
                    f"budget set {category.name} {format_money(limit_cents)} for {normalized_month}"
                ),
            },
        )

    return Budget(
        category_id=category.id,
        category_name=category.name,
        month=normalized_month,
        limit_cents=limit_cents,
    )


def summarize(conn: sqlite3.Connection, month: str) -> list[SummaryRow]:
    """Spend against budget for every category that has either, in one month."""
    normalized_month = validate_month(month)
    rows = conn.execute(
        "SELECT c.name AS category_name,"
        "       COALESCE(SUM(t.amount_cents), 0) AS spent_cents,"
        "       b.limit_cents AS limit_cents"
        " FROM categories c"
        " LEFT JOIN transactions t"
        "        ON t.category_id = c.id"
        "       AND t.deleted_at IS NULL"
        "       AND substr(t.occurred_on, 1, 7) = ?"
        " LEFT JOIN budgets b ON b.category_id = c.id AND b.month = ?"
        " GROUP BY c.id"
        " HAVING spent_cents != 0 OR limit_cents IS NOT NULL"
        " ORDER BY c.name COLLATE NOCASE",
        (normalized_month, normalized_month),
    ).fetchall()

    return [
        SummaryRow(
            category_name=row["category_name"],
            spent_cents=int(row["spent_cents"]),
            limit_cents=None if row["limit_cents"] is None else int(row["limit_cents"]),
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------


def last_journal_entry(conn: sqlite3.Connection) -> JournalEntry | None:
    """The most recent mutating command, undone or not."""
    row = conn.execute(
        "SELECT id, command, payload, created_at, undone_at"
        " FROM command_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return JournalEntry(
        id=row["id"],
        command=row["command"],
        payload=row["payload"],
        created_at=row["created_at"],
        undone_at=row["undone_at"],
    )


def undo(conn: sqlite3.Connection) -> str:
    """Reverse the most recent mutating command and describe what was reversed.

    Undo is single level by design: only the newest journal entry is ever eligible.
    That keeps the inverses trivially safe, because no later command can have built on
    the one being reversed.
    """
    entry = last_journal_entry(conn)
    if entry is None:
        raise NothingToUndoError("Nothing to undo.")
    if entry.undone_at is not None:
        raise NothingToUndoError("Nothing to undo. The last command has already been reversed.")

    payload = json.loads(entry.payload)
    description = str(payload.get("description", entry.command))

    with _transaction(conn):
        _apply_inverse(conn, entry.command, payload)
        conn.execute("UPDATE command_log SET undone_at = ? WHERE id = ?", (_now(), entry.id))

    return description


def _apply_inverse(conn: sqlite3.Connection, command: str, payload: dict[str, object]) -> None:
    if command in {"add", "import"}:
        transaction_ids = payload["transaction_ids"]
        if not isinstance(transaction_ids, list):
            raise MizanError("Journal entry is malformed and cannot be undone.")
        conn.executemany(
            "UPDATE transactions SET deleted_at = ? WHERE id = ?",
            [(_now(), transaction_id) for transaction_id in transaction_ids],
        )
    elif command == "category_add":
        conn.execute("DELETE FROM categories WHERE id = ?", (payload["category_id"],))
    elif command == "category_rename":
        conn.execute(
            "UPDATE categories SET name = ? WHERE id = ?",
            (payload["previous_name"], payload["category_id"]),
        )
    elif command == "budget_set":
        previous = payload["previous_limit_cents"]
        if previous is None:
            conn.execute(
                "DELETE FROM budgets WHERE category_id = ? AND month = ?",
                (payload["category_id"], payload["month"]),
            )
        else:
            conn.execute(
                "UPDATE budgets SET limit_cents = ? WHERE category_id = ? AND month = ?",
                (previous, payload["category_id"], payload["month"]),
            )
    else:  # pragma: no cover - only reachable if a command is journalled but not inverted
        raise MizanError(f"Cannot undo {command!r}.")


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _record(conn: sqlite3.Connection, command: str, payload: dict[str, object]) -> None:
    """Append to the command journal. Always called inside a transaction."""
    conn.execute(
        "INSERT INTO command_log (command, payload, created_at) VALUES (?, ?, ?)",
        (command, json.dumps(payload), _now()),
    )


@contextmanager
def _transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """Make a command all-or-nothing, journal entry included."""
    conn.execute("BEGIN")
    try:
        yield
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
