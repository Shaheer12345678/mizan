"""Shared fixtures.

Every fixture here points mizan at a throwaway database under ``tmp_path``. Nothing in
the suite touches the real one, which is the whole reason the database location is
driven by an environment variable.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from mizan import db, services
from mizan.cli import app

Invoke = Callable[..., Result]


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the database to a temporary file for one test."""
    path = tmp_path / "mizan.db"
    monkeypatch.setenv(db.DB_PATH_ENV_VAR, str(path))
    return path


@pytest.fixture
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    """An open connection to a fully migrated temporary database."""
    connection = db.connect(db_path)
    services.initialize(connection)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def seeded(conn: sqlite3.Connection) -> sqlite3.Connection:
    """A migrated database with two categories already in it."""
    services.add_category(conn, "groceries")
    services.add_category(conn, "transport")
    return conn


@pytest.fixture
def cli(db_path: Path) -> Invoke:
    """Invoke the real Typer app against the temporary database.

    COLUMNS is pinned wide because Rich wraps to the terminal width, and a long
    tmp_path can otherwise split a message across lines mid-sentence. That is correct
    behaviour in a real terminal but it makes assertions depend on how deep the
    temporary directory happens to be.
    """
    runner = CliRunner(env={db.DB_PATH_ENV_VAR: str(db_path), "COLUMNS": "200"})

    def invoke(*args: str) -> Result:
        return runner.invoke(app, list(args))

    return invoke
