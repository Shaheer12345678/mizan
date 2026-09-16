# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned

- Single file PyInstaller build published on tagged releases
- Recurring transactions
- JSON export alongside CSV

## [0.1.0] - 2026-09-15

First release.

### Added

- `mizan init`, which creates the database and applies pending migrations.
- `mizan add` to record an expense, with optional `--note` and `--date`.
- `mizan list`, filterable by `--month` and `--category`.
- `mizan summary`, showing spend against budget as a Rich table with an ASCII bar.
- `mizan budget set` for per category monthly limits.
- `mizan categories add`, `list` and `rename`. A rename keeps existing transactions
  attached.
- `mizan undo`, which reverses the most recent command that changed the database.
  Backed by a `command_log` journal. Reversing an `add` soft deletes rather than
  dropping the row, and an import is reversed as a single batch.
- `mizan export --format csv` and `mizan import FILE` for CSV round trips.
- `mizan db path`, and a `MIZAN_DB` environment variable to override the location.
- SQLite schema with a `schema_version` table and a migration runner that applies
  numbered `.sql` files in order, each in its own transaction.
- `PRAGMA foreign_keys = ON` on every connection.
- 137 tests covering money precision, migrations, services, rendering, the CLI, and
  CSV round trips.
- CI running ruff, mypy under `strict = true`, and pytest with an 85 percent coverage
  gate across Python 3.10, 3.11, 3.12 and 3.13.

### Notes

Money is stored as integer cents in an `INTEGER` column and never as a float. Parsing
goes through `Decimal`, and amounts with more than two decimal places are rejected
rather than rounded.

[Unreleased]: https://github.com/Shaheer12345678/mizan/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Shaheer12345678/mizan/releases/tag/v0.1.0
