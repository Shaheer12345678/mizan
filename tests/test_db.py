"""Where the database file lands, and what happens when a migration fails."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mizan import db


def test_the_environment_variable_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """This override is what keeps the test suite off the real database."""
    monkeypatch.setenv(db.DB_PATH_ENV_VAR, str(tmp_path / "custom.db"))

    assert db.default_db_path() == tmp_path / "custom.db"


def test_windows_uses_local_app_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(db.DB_PATH_ENV_VAR, raising=False)
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert db.default_db_path() == tmp_path / "mizan" / "mizan.db"


def test_other_platforms_use_the_xdg_data_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(db.DB_PATH_ENV_VAR, raising=False)
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    assert db.default_db_path() == tmp_path / "mizan" / "mizan.db"


def test_other_platforms_fall_back_to_the_home_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(db.DB_PATH_ENV_VAR, raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))

    assert db.default_db_path() == tmp_path / ".local" / "share" / "mizan" / "mizan.db"


def test_connect_creates_the_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "deeper" / "mizan.db"

    conn = db.connect(path)

    assert path.parent.is_dir()
    conn.close()


def test_a_failing_migration_leaves_the_version_unchanged(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken migration must not half apply, and must not claim it succeeded."""
    broken = db.Migration(version=1, name="001_broken.sql", sql="CREATE TABLE oops (;")
    monkeypatch.setattr(db, "available_migrations", lambda: [broken])
    conn = db.connect(db_path)

    with pytest.raises(sqlite3.Error):
        db.migrate(conn)

    assert db.current_version(conn) == 0
    assert not conn.in_transaction
    conn.close()
