-- Categories, transactions, and the command journal that backs `mizan undo`.

CREATE TABLE categories (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE transactions (
    id           INTEGER PRIMARY KEY,
    amount_cents INTEGER NOT NULL,
    category_id  INTEGER NOT NULL REFERENCES categories(id),
    occurred_on  TEXT NOT NULL,          -- ISO-8601 date
    note         TEXT,
    created_at   TEXT NOT NULL,
    deleted_at   TEXT                    -- soft delete, enables `undo`
);

CREATE INDEX idx_tx_date     ON transactions(occurred_on);
CREATE INDEX idx_tx_category ON transactions(category_id);

-- One row per mutating command. `payload` holds the JSON needed to invert it.
CREATE TABLE command_log (
    id         INTEGER PRIMARY KEY,
    command    TEXT NOT NULL,
    payload    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    undone_at  TEXT
);
