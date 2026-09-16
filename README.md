# mizan

A command line expense and budget tracker that stores money as integer cents, so the
numbers it shows you are the numbers it has.

[![ci](https://github.com/Shaheer12345678/mizan/actions/workflows/ci.yml/badge.svg)](https://github.com/Shaheer12345678/mizan/actions/workflows/ci.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python: 3.10 to 3.13](https://img.shields.io/badge/python-3.10%20to%203.13-blue.svg)](https://www.python.org/downloads/)

`mizan` is Arabic for a balance or a set of scales.

## Running it

```console
$ mizan init
Database ready at C:\Users\you\AppData\Local\mizan\mizan.db, schema version 2.

$ mizan categories add groceries
Added category groceries.

$ mizan add 12.50 groceries --note "milk and eggs" --date 2026-09-14
Added $12.50 to groceries on 2026-09-14.

# ... a few more categories, budgets and transactions, same commands ...

$ mizan summary --month 2026-09
Summary for 2026-09
+--------------------------------------------------------------+
| Category   |   Spent |  Budget | Used |                      |
|------------+---------+---------+------+----------------------|
| eating out |  $27.40 | $120.00 |  23% | #####............... |
| groceries  | $121.75 | $400.00 |  30% | ######.............. |
| transport  |  $30.00 |  $25.00 | 120% | #################### |
|------------+---------+---------+------+----------------------|
| Total      | $179.15 | $545.00 |      |                      |
+--------------------------------------------------------------+

$ mizan list --month 2026-09 --category groceries
Transactions
+-------------------------------------------------------+
| ID | Date       | Category  |  Amount | Note          |
|----+------------+-----------+---------+---------------|
|  5 | 2026-09-21 | groceries |  $61.05 | weekly shop   |
|  4 | 2026-09-14 | groceries |  $12.50 | milk and eggs |
|  1 | 2026-09-02 | groceries |  $48.20 |               |
|----+------------+-----------+---------+---------------|
|    |            | Total     | $121.75 |               |
+-------------------------------------------------------+

$ mizan undo
Undid: add $61.05 groceries on 2026-09-21
```

Over-budget categories turn red, and anything past 90 percent turns yellow. The bar is
drawn in ASCII so it looks the same in a bare Windows console as it does anywhere else.

## Why this exists

Every budgeting app I tried wanted an account login before it would let me write down
that I spent twelve dollars on groceries. I wanted the opposite: something that opens in
the time it takes to type eight characters, keeps its data in a single file I own, and
never asks me to sign in to see my own spending.

The second reason is narrower. A budget tool that stores money as a floating point
number is quietly wrong, and most small ones do. This one is built to be right about
that, and the reasoning is written down below rather than assumed.

## Quickstart

```bash
pip install git+https://github.com/Shaheer12345678/mizan.git
mizan init
mizan categories add groceries
mizan add 12.50 groceries --note "milk"
mizan summary
```

`mizan db path` prints where the database file lives. Set `MIZAN_DB` to put it
somewhere else, which is also how the test suite keeps off your real data.

### Commands

| Command | What it does |
|---|---|
| `mizan init` | Create the database and apply pending migrations |
| `mizan add AMOUNT CATEGORY [--note] [--date]` | Record an expense |
| `mizan list [--month] [--category]` | List transactions, newest first |
| `mizan summary [--month]` | Spend against budget, with a bar |
| `mizan budget set CATEGORY AMOUNT [--month]` | Set a monthly limit |
| `mizan categories add\|list\|rename` | Manage categories |
| `mizan undo` | Reverse the last command that changed anything |
| `mizan export --format csv [--output FILE]` | Write transactions as CSV |
| `mizan import FILE` | Read transactions from CSV |
| `mizan db path` | Print the database location |

## Architecture

```
cli.py         Typer commands. Parse, call a service, render. Nothing else.
render.py      Rich tables and the ASCII budget bar.
  |
services.py    All business logic. No Typer import, no Rich import.
  |
db.py          Connection, pragmas, migration runner.
money.py       Dollar strings in, integer cents out.
models.py      Frozen dataclasses passed between the layers.
importers.py   CSV in and out.
migrations/    Numbered .sql files, applied in order.
```

### Money is stored as integer cents

`0.1 + 0.2` is not `0.3` in IEEE 754, and no amount of careful rounding downstream fixes
that. A tool that loses a fraction of a cent per transaction is broken in the one way
its users are guaranteed to notice, because reconciling against a bank statement is the
entire job.

So `amount_cents` is an `INTEGER` column. Parsing goes `str -> Decimal -> int` and never
constructs a float at any point. Dollars exist only in `format_money`, at the moment
something is printed. The parser also refuses amounts with more than two decimal places
instead of rounding them, because silently rounding is the exact failure the design is
meant to prevent.

The proof is a test, not a claim: `test_sum_of_1000_one_cent_amounts_is_exactly_ten_dollars`
sums a thousand parses of `"0.01"` and asserts exactly `1000` cents. Its neighbour does
the same sum in floats and asserts the result is not `10.00`.

### Business logic knows nothing about the CLI

`services.py` imports neither Typer nor Rich. That is not a style preference, it buys
two things. The service tests run against a real SQLite database without going through a
CLI runner, which is why the suite finishes in about three seconds. And adding a second
frontend later would not mean rewriting any logic.

This is enforced rather than trusted. One test reads the module source for those
imports, and a second imports `mizan.services` in a subprocess and asserts that neither
`typer` nor `rich` ended up in `sys.modules`, which catches them arriving indirectly.

### Migrations

A `schema_version` table holds a single integer. The runner creates it, reads it, and
applies every numbered `.sql` file above that number, each inside its own transaction.
The version table is owned by the runner rather than by `001_initial.sql`, because the
runner has to know the version before it can decide what to apply.

Two migrations exist today: `001_initial.sql` for categories, transactions and the
command journal, and `002_budgets.sql` for monthly limits. Tests cover both a fresh
database and the v1 to v2 upgrade with existing rows in it.

`PRAGMA foreign_keys = ON` runs on every connection. SQLite does not enforce foreign
keys by default, and the setting is per connection rather than stored in the file, so
setting it once at creation would do nothing.

### How undo works

Every mutating command appends a row to `command_log` holding the JSON needed to invert
it. `undo` reads the newest row, applies the inverse and stamps `undone_at`.

Undo is deliberately single level. Only the newest entry is ever eligible, so no later
command can have built on the one being reversed, which makes every inverse safe without
any dependency tracking. A second `undo` says there is nothing left to reverse.

Reversing an `add` sets `deleted_at` rather than deleting the row, so the history stays
intact and only the queries filter it out. An import is journalled as a single entry, so
undoing a 200 row import removes all 200 rather than leaving a partial ledger.

## Testing

```bash
pip install -e ".[dev]"
pytest --cov=mizan --cov-report=term-missing
```

**137 tests, 98 percent line coverage.** CI runs the suite on Python 3.10, 3.11, 3.12
and 3.13, and gates on `ruff format --check`, `ruff check`, `mypy` under `strict = true`,
and a coverage floor of 85 percent.

| File | Covers |
|---|---|
| `test_money.py` | Parsing, formatting, and the float precision proofs |
| `test_db.py` | Database location per platform, failed migration rollback |
| `test_migrations.py` | Fresh migrate, v1 to v2 upgrade, foreign key enforcement |
| `test_services.py` | Categories, transactions, budgets, summary, undo |
| `test_render.py` | Tables and the budget bar |
| `test_cli.py` | Every command through Typer's `CliRunner` |
| `test_import_export.py` | CSV round trip, malformed rows, batch undo |

## Results

- A thousand transactions of one cent sum to exactly `$10.00`. The same sum in floats
  does not.
- The full suite runs in about 3 seconds, because most of it never touches the CLI.
- Zero `ruff` and `mypy` findings under `strict = true` across 4 Python versions.

## Roadmap

- [ ] Single file PyInstaller build published on tagged releases
- [ ] Recurring transactions
- [ ] JSON export alongside CSV
- [ ] Multi step undo, once there is a reason to want it
