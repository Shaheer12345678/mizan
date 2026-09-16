-- Per-category monthly spending limits.

CREATE TABLE budgets (
    category_id  INTEGER NOT NULL REFERENCES categories(id),
    month        TEXT NOT NULL,          -- 'YYYY-MM'
    limit_cents  INTEGER NOT NULL,
    PRIMARY KEY (category_id, month)
);
