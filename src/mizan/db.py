"""Connection setup and the migration runner.

No ORM. The schema is small enough that raw SQL is clearer than a mapping layer, and
the migration runner is about forty lines.
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys
from importlib import resources
from pathlib import Path
from typing import NamedTuple

__all__ = [
    "DB_PATH_ENV_VAR",
    "Migration",
    "available_migrations",
    "connect",
    "current_version",
    "default_db_path",
    "migrate",
]

DB_PATH_ENV_VAR = "MIZAN_DB"

_MIGRATION_NAME = re.compile(r"^(\d+)_.+\.sql$")


class Migration(NamedTuple):
    version: int
    name: str
    sql: str


def default_db_path() -> Path:
    """Where the database lives when the environment does not say otherwise.

    ``MIZAN_DB`` wins if it is set, which is what keeps the test suite off the real
    database. Otherwise this follows the platform convention.
    """
    override = os.environ.get(DB_PATH_ENV_VAR)
    if override:
        return Path(override).expanduser()

    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")

    return base / "mizan" / "mizan.db"


def connect(path: Path) -> sqlite3.Connection:
    """Open a connection with the pragmas this schema depends on.

    SQLite does not enforce foreign keys unless asked, and the setting is per
    connection rather than per database, so it has to happen here every time.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def available_migrations() -> list[Migration]:
    """Every bundled migration, ordered by version."""
    migrations = []
    # Addressed as a data directory inside the mizan package rather than as a
    # subpackage, because it holds only .sql files and no __init__.py.
    for entry in resources.files("mizan").joinpath("migrations").iterdir():
        match = _MIGRATION_NAME.match(entry.name)
        if match is None:
            continue
        migrations.append(
            Migration(version=int(match.group(1)), name=entry.name, sql=entry.read_text("utf-8"))
        )

    migrations.sort(key=lambda migration: migration.version)
    return migrations


def current_version(conn: sqlite3.Connection) -> int:
    """Schema version of this database. Zero means nothing has been applied yet."""
    _ensure_version_table(conn)
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    return int(row["version"])


def migrate(conn: sqlite3.Connection, *, target: int | None = None) -> int:
    """Apply every pending migration in order and return the resulting version.

    Each migration runs inside its own transaction, so a failure part way through
    leaves the database on the last version that fully applied rather than in a
    half-migrated state. Applying an up to date database is a no-op.
    """
    version = current_version(conn)

    for migration in available_migrations():
        if migration.version <= version:
            continue
        if target is not None and migration.version > target:
            break

        # The BEGIN has to be inside the script. executescript commits any transaction
        # that is already open before it runs, so opening one beforehand would be undone.
        try:
            conn.executescript(f"BEGIN;\n{migration.sql}")
            conn.execute("UPDATE schema_version SET version = ?", (migration.version,))
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        version = migration.version

    return version


def _ensure_version_table(conn: sqlite3.Connection) -> None:
    """Create and seed the version table.

    This lives in the runner rather than in 001, because the runner has to read the
    version before it can decide which migration files to apply.
    """
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    if conn.execute("SELECT COUNT(*) AS n FROM schema_version").fetchone()["n"] == 0:
        conn.execute("INSERT INTO schema_version (version) VALUES (0)")
