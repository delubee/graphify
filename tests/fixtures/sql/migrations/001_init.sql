CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY,
    table_name TEXT NOT NULL,
    event TEXT NOT NULL
);

UPDATE orders
SET total_cents = total_cents + 1
WHERE id = 1;
