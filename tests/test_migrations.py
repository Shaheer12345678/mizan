"""Migration runner: a fresh database, an upgrade from v1 to v2, and the pragmas."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mizan import db

LATEST_VERSION = 2


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def test_migrations_are_discovered_in_version_order() -> None:
    migrations = db.available_migrations()

    assert [migration.version for migration in migrations] == [1, 2]
    assert migrations[0].name == "001_initial.sql"
    assert migrations[1].name == "002_budgets.sql"


def test_fresh_database_migrates_to_the_latest_version(db_path: Path) -> None:
    conn = db.connect(db_path)

    assert db.current_version(conn) == 0
    assert db.migrate(conn) == LATEST_VERSION
    assert db.current_version(conn) == LATEST_VERSION

    for table in ("categories", "transactions", "budgets", "command_log", "schema_version"):
        assert _table_exists(conn, table), table
    conn.close()


def test_migrating_an_up_to_date_database_changes_nothing(db_path: Path) -> None:
    conn = db.connect(db_path)
    db.migrate(conn)
    before = conn.execute("SELECT COUNT(*) AS n FROM sqlite_master").fetchone()["n"]

    assert db.migrate(conn) == LATEST_VERSION
    assert conn.execute("SELECT COUNT(*) AS n FROM sqlite_master").fetchone()["n"] == before
    conn.close()


def test_stopping_at_v1_leaves_budgets_unbuilt(db_path: Path) -> None:
    conn = db.connect(db_path)

    assert db.migrate(conn, target=1) == 1
    assert _table_exists(conn, "categories")
    assert not _table_exists(conn, "budgets")
    conn.close()


def test_upgrading_v1_to_v2_adds_budgets_and_keeps_existing_rows(db_path: Path) -> None:
    """The upgrade path someone on an older build actually takes."""
    conn = db.connect(db_path)
    db.migrate(conn, target=1)
    conn.execute("INSERT INTO categories (name) VALUES ('groceries')")
    conn.execute(
        "INSERT INTO transactions (amount_cents, category_id, occurred_on, created_at)"
        " VALUES (1250, 1, '2026-09-14', '2026-09-14T00:00:00+00:00')"
    )

    assert db.migrate(conn) == LATEST_VERSION
    assert _table_exists(conn, "budgets")
    assert conn.execute("SELECT name FROM categories").fetchone()["name"] == "groceries"
    assert conn.execute("SELECT amount_cents FROM transactions").fetchone()["amount_cents"] == 1250
    conn.close()


def test_foreign_key_enforcement_is_switched_on(conn: sqlite3.Connection) -> None:
    """SQLite leaves foreign keys off unless each connection asks for them."""
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_a_transaction_cannot_reference_a_missing_category(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO transactions (amount_cents, category_id, occurred_on, created_at)"
            " VALUES (1250, 999, '2026-09-14', '2026-09-14T00:00:00+00:00')"
        )


def test_amount_column_is_an_integer(conn: sqlite3.Connection) -> None:
    """Money is stored as INTEGER cents, which is what rules float drift out."""
    columns = {row["name"]: row["type"] for row in conn.execute("PRAGMA table_info(transactions)")}

    assert columns["amount_cents"] == "INTEGER"
