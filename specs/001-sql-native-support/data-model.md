# Phase 1 Data Model: SQL Native Support

**Feature**: 001-sql-native-support
**Date**: 2026-04-24

Defines the node and edge shapes that `extract_sql()` emits into the shared graph.
Shapes are additive to graphify's existing node/edge model — no migration of existing
graphs is required.

## Conventions

- All node objects are JSON-serializable dicts matching graphify's existing
  node shape: `{"id": str, "type": str, "label": str, ...attrs}`.
- All edge objects match graphify's existing shape:
  `{"source": str, "target": str, "relation": str, "confidence": str,
    "source_file": str, "source_location": str, "weight": float}`.
- `confidence` uses the existing vocabulary: `"EXTRACTED"`, `"INFERRED"`,
  `"AMBIGUOUS"`. Per FR-020, every SQL node/edge carries one of these.

## Node types

### `sql_file`

Represents a `.sql` file on disk.

| Field             | Type             | Required | Notes                                         |
|-------------------|------------------|----------|-----------------------------------------------|
| `id`              | `str`            | yes      | `_make_id("file", path)`                      |
| `type`            | `"sql_file"`     | yes      |                                               |
| `label`           | `str`            | yes      | Relative path, e.g. `db/migrations/001_init.sql` |
| `path`            | `str`            | yes      | Same as `label`; kept for parity with other file nodes |
| `sha256`          | `str`            | yes      | 64-char hex; matches the cache key            |
| `statement_count` | `int`            | yes      | Number of `statement` nodes attached          |
| `parse_status`    | `"ok" \| "partial" \| "failed"` | yes | See parse-failure rules below |
| `parser_error`    | `str`            | optional | Present only when `parse_status != "ok"`     |
| `default_schema`  | `str`            | yes      | Schema used for unqualified refs; `"public"` by default |

### `statement`

One top-level SQL statement.

| Field             | Type              | Required | Notes                                        |
|-------------------|-------------------|----------|----------------------------------------------|
| `id`              | `str`             | yes      | `_make_id("stmt", path, str(index))`          |
| `type`            | `"statement"`     | yes      |                                              |
| `label`           | `str`             | yes      | e.g. `"SELECT from users (L12)"`              |
| `statement_type`  | `str`             | yes      | Uppercase: `CREATE_TABLE`, `ALTER_TABLE`, `CREATE_VIEW`, `CREATE_MATERIALIZED_VIEW`, `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `WITH`, `CREATE_FUNCTION`, `CREATE_PROCEDURE`, `UNKNOWN` |
| `line_start`      | `int`             | yes      | 1-indexed                                    |
| `line_end`        | `int`             | yes      | 1-indexed                                    |
| `text_snippet`    | `str`             | yes      | Normalized (whitespace collapsed); truncated to 300 chars |
| `parse_status`    | `"ok" \| "partial" \| "failed"` | yes | Per-statement status  |

### `table`

A named base table, as defined by `CREATE TABLE` or referenced by DML.

| Field             | Type         | Required | Notes                                        |
|-------------------|--------------|----------|----------------------------------------------|
| `id`              | `str`        | yes      | `_make_id("table", schema_name, object_name)` |
| `type`            | `"table"`    | yes      |                                              |
| `label`           | `str`        | yes      | e.g. `"public.users"`                         |
| `schema_name`     | `str`        | yes      | Lowercased if unquoted; preserved if quoted  |
| `object_name`     | `str`        | yes      | Same casing rule                             |
| `qualified_name`  | `str`        | yes      | `schema.object`                              |
| `defining_file`   | `str`        | optional | Path to the `.sql` file where `CREATE TABLE` was seen, if any |

### `view`, `materialized_view`

Same shape as `table`. `type` is `"view"` or `"materialized_view"` respectively.
`materialized_view` is a separate `type` (not a flag on `view`) so downstream filters
can treat them distinctly.

### `column`

A column on a table, view, or materialized view.

| Field             | Type         | Required | Notes                                        |
|-------------------|--------------|----------|----------------------------------------------|
| `id`              | `str`        | yes      | `_make_id("col", schema_name, object_name, column_name)` |
| `type`            | `"column"`   | yes      |                                              |
| `label`           | `str`        | yes      | e.g. `"public.users.email"`                    |
| `parent_table_id` | `str`        | yes      | ID of the owning `table`/`view`/`materialized_view` |
| `schema_name`     | `str`        | yes      |                                              |
| `object_name`     | `str`        | yes      | Parent table/view name                        |
| `column_name`     | `str`        | yes      |                                              |
| `qualified_name`  | `str`        | yes      | `schema.object.column`                        |
| `declared_type`   | `str`        | optional | Best-effort: `"INTEGER"`, `"TEXT"`, `"TIMESTAMP WITH TIME ZONE"`, `"VARCHAR(255)"`, ... |

### `cte`

A Common Table Expression declared in a `WITH ...` clause. Scoped to its enclosing
statement — CTEs are not globally addressable (FR-019).

| Field                    | Type         | Required | Notes                                        |
|--------------------------|--------------|----------|----------------------------------------------|
| `id`                     | `str`        | yes      | `_make_id("cte", path, str(stmt_index), cte_name)` |
| `type`                   | `"cte"`      | yes      |                                              |
| `label`                  | `str`        | yes      | e.g. `"WITH active_users (L22)"`              |
| `cte_name`               | `str`        | yes      |                                              |
| `enclosing_statement_id` | `str`        | yes      | ID of the parent `statement` node             |

### `sql_function`, `sql_procedure` (Phase 3)

Reserved node types. Not populated in Phase 1 or 2. Same shape as `table` (with
`qualified_name`) plus:

| Field          | Type   | Notes                                           |
|----------------|--------|-------------------------------------------------|
| `return_type`  | `str`  | Optional; for `sql_function` only               |
| `arg_count`    | `int`  | Optional                                        |

## Edge types

Every edge carries `source_file` (the `.sql` path), `source_location` (`"L<n>"`),
`confidence` (see Conventions), and `weight` (default `1.0`).

| Relation            | Phase | Source type      | Target type                             | Emitted when                                          |
|---------------------|-------|------------------|-----------------------------------------|-------------------------------------------------------|
| `contains`          | 1     | `sql_file`       | `statement`                             | Every parsed statement                                |
| `defines`           | 1     | `sql_file`       | `table`, `view`, `materialized_view`    | `CREATE TABLE/VIEW/MATERIALIZED VIEW`                 |
| `selects_from`      | 1     | `statement`      | `table`, `view`, `materialized_view`    | `SELECT ... FROM X` (per source relation)              |
| `joins`             | 1     | `statement`      | `table`, `view`, `materialized_view`    | Any `JOIN` in the statement                           |
| `inserts_into`      | 1     | `statement`      | `table`                                 | `INSERT INTO X`                                        |
| `updates`           | 1     | `statement`      | `table`                                 | `UPDATE X`                                             |
| `deletes_from`      | 1     | `statement`      | `table`                                 | `DELETE FROM X`                                        |
| `has_column`        | 1     | `table`/`view`/`materialized_view` | `column`                | Column declared in `CREATE TABLE`/`CREATE VIEW AS ...` |
| `depends_on`        | 1     | `view`/`materialized_view` | `table`/`view`/`materialized_view` | `CREATE VIEW ... AS SELECT ... FROM X` |
| `uses_cte`          | 1     | `statement`      | `cte`                                   | CTE referenced (from subquery in main SELECT)          |
| `references`        | 1     | `table`/`column` | `table`/`column`                        | Foreign keys: `REFERENCES other(col)` in `CREATE TABLE` |
| `executes`          | 3     | *code function*  | `statement`                             | Phase 3 embedded-SQL detection                         |
| `derives_from`      | 3     | `column`         | `column`                                | Phase 3 column-level lineage                           |

### Edge provenance rules

- `contains`, `defines`, `has_column`, `references`: **`EXTRACTED`** — syntactic
  facts present in the text.
- `selects_from`, `joins`, `inserts_into`, `updates`, `deletes_from`, `depends_on`,
  `uses_cte`: **`EXTRACTED`** if the identifier is qualified; **`INFERRED`** if it
  was resolved via the default-schema rule (R-004).
- `executes` (Phase 3): **`INFERRED`** for DB-API / SQLAlchemy patterns;
  **`AMBIGUOUS`** for heuristic-matched string literals.
- `derives_from` (Phase 3): **`INFERRED`** by default; **`AMBIGUOUS`** when
  crossing set operations (UNION) or recursive CTEs.

## Invariants

1. **Stable IDs**: Re-running extraction on identical file contents produces
   identical node and edge IDs (tested in `test_sql_extract.py::test_id_stability`).
2. **No dangling edges**: Every edge's `source` and `target` MUST refer to a node
   emitted by this extraction or present in the existing graph. Extractor emits
   referenced table/column nodes even when they're not defined in any `.sql` file
   in the corpus (e.g., `SELECT * FROM external_table`) — with
   `defining_file = null` and `confidence = "INFERRED"`.
3. **Dedup correctness**: Two references to `public.users` from different files
   produce edges to the *same* `table:public_users` node — the dedup logic is
   already provided by ID-based node merging in `build.py`.
4. **CTE locality**: A `cte` node's `enclosing_statement_id` MUST match an
   emitted `statement` ID. CTEs are never shared across statements even if the
   names collide (per FR-019).
5. **`parse_status` consistency**: `sql_file.parse_status == "ok"` iff every
   child `statement.parse_status == "ok"`; `"partial"` iff at least one parses
   and at least one does not; `"failed"` iff zero statements parsed.
6. **Graphify-out exclusion**: `extract_sql()` MUST never be called on a path
   under `graphify-out/`. (Enforced upstream in `detect.py`; re-verified as an
   invariant test.)

## Validation rules

- `statement_count` == `len([s for s in statements if s.parse_status != "failed"])`
  ∪ failed statements — i.e., the count reflects all attempted statements.
- `schema_name`, `object_name`, `column_name` MUST NOT be empty strings.
- `line_start <= line_end`, both 1-indexed.
- `text_snippet` truncated at 300 chars; if truncated, ends with `"…"`.
- `qualified_name` always matches `f"{schema_name}.{object_name}"` (and for
  columns `f"{schema}.{object}.{column}"`).

## State transitions

SQL entities have no runtime state transitions — extraction is stateless and
deterministic. The only "state" is the parse status per file/statement, which
is set once and never changes within a run. A re-run on a modified file
discards prior extraction (cache miss) and re-emits fresh nodes/edges.

## Size bounds (SC-008 sanity check)

Given a `.sql` corpus with S statements, T unique tables, V unique views, C unique
columns, K unique CTEs across files:

- Node count: `1 file per SQL path` + `S statements` + `T tables` + `V views` +
  `C columns` + `K cte`s = **O(S + T + V + C + K)**.
- Edge count: bounded by `O(S × avg_tables_per_stmt)` — typically ≤ 5×S.

For the reference 10k-statement corpus with ~200 tables and ~2000 columns:
roughly **12–15k nodes, 50k edges**. Well within graphify's existing scale.
