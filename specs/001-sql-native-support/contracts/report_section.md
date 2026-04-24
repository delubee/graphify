# Contract: `GRAPH_REPORT.md` SQL Overview section

**Feature**: 001-sql-native-support
**Module**: `graphify/report.py` (new `_render_sql_overview` helper)
**Phase**: 2

## Placement

- Inserted between the existing "God Nodes" section and "Surprising Connections"
  section of `GRAPH_REPORT.md`.
- Omitted entirely (no empty stub, no heading) when the graph contains zero
  SQL nodes (FR-025).

## Shape

```markdown
## SQL Overview

_NN statements across NN .sql files. Default schema: `public`._

### Most-referenced tables

| Table                   | Selects | Mutations | Defined in                    |
|-------------------------|---------|-----------|-------------------------------|
| `public.users`          | 142     | 8         | `db/migrations/001_init.sql`  |
| `public.orders`         | 87      | 23        | `db/migrations/002_orders.sql` |
| `analytics.events`      | 54      | 12        | *(not found in corpus)*       |
| ...                     |         |           |                               |

### Most-mutated tables

| Table                   | Inserts | Updates | Deletes | Total |
|-------------------------|---------|---------|---------|-------|
| `public.audit_log`      | 201     | 0       | 0       | 201   |
| `public.orders`         | 45      | 12      | 3       | 60    |
| ...                     |         |         |         |       |

### Views by dependency fan-in

| View                       | Depends on | Defined in                     |
|----------------------------|------------|--------------------------------|
| `public.daily_revenue`     | 7 tables   | `db/views/daily_revenue.sql`   |
| `public.user_activity`     | 4 tables   | `db/views/user_activity.sql`   |
| ...                        |            |                                |

### SQL hotspots by file

| File                                   | Statements | Tables referenced |
|----------------------------------------|------------|-------------------|
| `db/queries/reports.sql`               | 34         | 12                |
| `db/migrations/010_big_refactor.sql`   | 28         | 9                 |
| ...                                    |            |                   |
```

## Ranking rules

- **Most-referenced tables**: sorted by count of incoming `selects_from` +
  `joins` edges. Ties broken by `qualified_name` ascending. Top 10 shown.
- **Most-mutated tables**: sorted by count of incoming `inserts_into` +
  `updates` + `deletes_from` edges. Top 10 shown.
- **Views by fan-in**: sorted by count of outgoing `depends_on` edges. Top 10
  shown.
- **SQL hotspots**: sorted by `statement_count` per file (descending). Top 10
  shown.

## Suggested Questions contract (FR-024)

The existing "Suggested Questions" block at the bottom of `GRAPH_REPORT.md`
MUST gain at least 3 SQL-oriented questions when the graph contains SQL nodes:

- "Which tables are written to by the most code paths?"
- "Which views fan out to the largest number of base tables?"
- "Are there tables defined in the schema but never referenced by any query?"

And may include additional context-specific ones derived from the corpus, e.g.:
- "Which SQL files contain the most statements? What do they do?"
- "Are there any tables referenced but never defined in the corpus?"

## Omit-on-empty rule

If `sum(1 for n in nodes if n["type"] == "sql_file") == 0`, the `_render_sql_overview`
helper MUST return `None`, and the caller MUST NOT emit the `## SQL Overview`
heading at all. This preserves the report for users with no `.sql` files
(SC-009: "no empty SQL sections in the report").

## Row-limit sanity

On a repo with 1000+ tables, each subsection is capped at 10 rows with an
"(and N more)" footnote. This keeps the report readable (constitution III,
actionable output).

## Localization

Not in scope for Phase 2. All section text is English. (graphify already has
translated README files but not translated reports.)

## Test assertions

`tests/test_sql_report.py` MUST cover:

- A repo with SQL → "SQL Overview" section present, tables populated.
- A repo without SQL → no "SQL Overview" heading anywhere in the report.
- Ranking correctness: given a fixture with known counts, the top-10 tables
  appear in the documented order.
- Suggested Questions: at least 3 SQL-flavored questions present when
  SQL nodes exist; none when they don't.
