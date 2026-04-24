# Quickstart: SQL Native Support

**Feature**: 001-sql-native-support
**Date**: 2026-04-24
**Audience**: Developer validating the implementation end-to-end.

This walkthrough is the executable acceptance scenario for the feature. If all
steps pass on each of the three phased milestones, the feature meets its spec.

## Prerequisites

- Python 3.10+ environment with graphify installed from the local checkout
  (`pip install -e .` from the repo root).
- `sqlglot >= 25.0.0` installed (becomes a hard dependency of graphify with
  this feature).
- A scratch directory: `/tmp/graphify-sql-quickstart`.

## Fixture setup

```bash
mkdir -p /tmp/graphify-sql-quickstart/{db/migrations,db/views,db/queries}
cd /tmp/graphify-sql-quickstart

# schema
cat > db/migrations/001_init.sql <<'SQL'
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE
);

CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    total_cents INTEGER NOT NULL,
    placed_at TIMESTAMP WITH TIME ZONE
);
SQL

# view
cat > db/views/active_users.sql <<'SQL'
CREATE VIEW active_users AS
SELECT u.id, u.email
FROM users u
JOIN orders o ON o.user_id = u.id
WHERE o.placed_at > NOW() - INTERVAL '30 days';
SQL

# queries
cat > db/queries/reports.sql <<'SQL'
WITH recent_orders AS (
    SELECT user_id, SUM(total_cents) AS spend
    FROM orders
    WHERE placed_at > NOW() - INTERVAL '30 days'
    GROUP BY user_id
)
SELECT u.email, r.spend
FROM users u
JOIN recent_orders r ON r.user_id = u.id
ORDER BY r.spend DESC
LIMIT 10;

INSERT INTO audit_log (table_name, event) VALUES ('orders', 'monthly_report_run');
SQL

# malformed
cat > db/migrations/002_broken.sql <<'SQL'
CREATE TABLE good_one (id INT);
THIS_IS_NOT_SQL @@@;
CREATE TABLE also_good (id INT);
SQL
```

## Phase 1 validation — Detection & Extraction (US1, MVP)

Run extraction:

```bash
cd /tmp/graphify-sql-quickstart
graphify update .
```

**Expected**:

1. `graphify-out/graph.json` exists and contains SQL nodes. Verify with:

   ```bash
   jq '.nodes | map(select(.type | startswith("sql_") or . == "statement" or . == "table" or . == "view" or . == "column" or . == "cte")) | length' graphify-out/graph.json
   # Expect: > 10
   ```

2. `sql_file` nodes for every `.sql` file:

   ```bash
   jq '.nodes | map(select(.type == "sql_file")) | map(.label)' graphify-out/graph.json
   # Expect: ["db/migrations/001_init.sql", "db/migrations/002_broken.sql", "db/views/active_users.sql", "db/queries/reports.sql"]
   ```

3. Table nodes for `users`, `orders`, `good_one`, `also_good`, `audit_log`:

   ```bash
   jq '.nodes | map(select(.type == "table")) | map(.qualified_name) | sort' graphify-out/graph.json
   # Expect: ["public.also_good", "public.audit_log", "public.good_one", "public.orders", "public.users"]
   ```

4. View node for `active_users`:

   ```bash
   jq '.nodes | map(select(.type == "view" and .object_name == "active_users"))' graphify-out/graph.json
   # Expect: one entry with qualified_name "public.active_users"
   ```

5. `depends_on` edge `active_users → users` and `active_users → orders`:

   ```bash
   jq '.links | map(select(.relation == "depends_on" and ._src == "view_public_active_users")) | map(._tgt) | sort' graphify-out/graph.json
   # Expect: ["table_public_orders", "table_public_users"]
   ```

6. CTE node for `recent_orders`:

   ```bash
   jq '.nodes | map(select(.type == "cte" and .cte_name == "recent_orders"))' graphify-out/graph.json
   # Expect: exactly one entry
   ```

7. **Graceful degradation**: `002_broken.sql` is present with `parse_status =
   "partial"`, and both `good_one` and `also_good` tables are still extracted:

   ```bash
   jq '.nodes | map(select(.label == "db/migrations/002_broken.sql")) | map(.parse_status)' graphify-out/graph.json
   # Expect: ["partial"]

   jq '.nodes | map(select(.qualified_name == "public.good_one" or .qualified_name == "public.also_good"))' graphify-out/graph.json
   # Expect: two entries
   ```

8. **`.graphifyignore`** respected:

   ```bash
   echo "db/queries/" > .graphifyignore
   rm -rf graphify-out/
   graphify update .
   jq '.nodes | map(select(.label | startswith("db/queries/"))) | length' graphify-out/graph.json
   # Expect: 0
   ```

9. **Cache hit on re-run**: `graphify update .` a second time is near-instant (cache
   hits). No new nodes.

## Phase 2 validation — Analysis & Report (US2)

```bash
cd /tmp/graphify-sql-quickstart
rm -rf graphify-out/ .graphifyignore
graphify update .
cat graphify-out/GRAPH_REPORT.md | head -200
```

**Expected**:

1. A `## SQL Overview` section is present.
2. It contains `### Most-referenced tables` with `public.users` and
   `public.orders` in the top rows.
3. It contains `### Most-mutated tables` with `public.audit_log`.
4. It contains `### Views by dependency fan-in` with `public.active_users`
   (depends on `users` and `orders`, fan-in = 2).
5. The `Suggested Questions` block contains at least 3 SQL-oriented questions.
6. On a repo with no `.sql` files (try `graphify update /tmp/empty-repo`), the
   `## SQL Overview` section is **absent** from `GRAPH_REPORT.md`.

## Phase 3 validation — Embedded SQL & Column Lineage (US3)

Add a Python file and a SQL query projecting named columns:

```bash
cat > app.py <<'PY'
import sqlite3
def recent_emails(conn: sqlite3.Connection) -> list[str]:
    cur = conn.execute("SELECT email FROM users WHERE created_at > '2026-01-01'")
    return [row[0] for row in cur.fetchall()]
PY

cat > db/views/revenue.sql <<'SQL'
CREATE VIEW monthly_revenue AS
SELECT o.user_id, SUM(o.total_cents) AS total
FROM orders o
GROUP BY o.user_id;
SQL

rm -rf graphify-out/
graphify update . --sql-embedded --sql-lineage
```

**Expected**:

1. An `executes` edge from the `recent_emails` function node to a synthesized
   `statement` node:

   ```bash
   jq '.links | map(select(.relation == "executes"))' graphify-out/graph.json
   # Expect: at least one edge ending at a statement node whose text_snippet starts with "SELECT email FROM users"
   ```

2. A `selects_from` edge from that synthesized statement to `table:public_users`:

   ```bash
   jq '.links | map(select(.relation == "selects_from" and (._src | startswith("stmt_app_py_embedded_app_recent_emails_")) and ._tgt == "table_public_users"))' graphify-out/graph.json
   # Expect: at least one entry
   ```

3. A `derives_from` edge from `column:public_monthly_revenue_total` to
   `column:public_orders_total_cents`:

   ```bash
   jq '.links | map(select(.relation == "derives_from" and ._src == "col_public_monthly_revenue_total" and ._tgt == "col_public_orders_total_cents"))' graphify-out/graph.json
   # Expect: at least one such edge
   ```

4. With the flags **omitted** (bare `graphify update .`), none of the above
   edges/nodes are produced — Phase 3 is opt-in only.

## Performance validation (SC-007)

```bash
# Prepare benchmark corpora
python .specify/scripts/prepare_sql_benchmark.py /tmp/bench-nosql /tmp/bench-withsql

# Baseline (no-sql)
time graphify update /tmp/bench-nosql

# With SQL
time graphify update /tmp/bench-withsql
```

**Expected**: `bench-withsql` wall-clock ≤ `bench-nosql` × 1.15 (15% ceiling
per SC-007). CI gate `tests/test_sql_benchmark.py` enforces this.

## Watch mode validation (SC-005)

```bash
graphify watch &
sleep 2
echo "CREATE TABLE new_table (id INT);" >> db/migrations/001_init.sql
sleep 3
jq '.nodes | map(select(.qualified_name == "public.new_table"))' graphify-out/graph.json
# Expect: one entry (added within one incremental cycle)
kill %1
```

## Rollback

To cleanly remove the feature from a repo after testing:

```bash
rm -rf graphify-out/ /tmp/graphify-sql-quickstart
```

The feature does not modify any user files outside `graphify-out/`, so
rollback is idempotent.
