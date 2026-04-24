# Phase 0 Research: SQL Native Support

**Feature**: 001-sql-native-support
**Date**: 2026-04-24
**Purpose**: Resolve all technical unknowns and pin dependencies before Phase 1 design.

All decisions use the format:
- **Decision**: what was chosen
- **Rationale**: why
- **Alternatives considered**: what else was evaluated and why rejected

---

## R-001 Primary SQL parser

- **Decision**: `sqlglot >= 25.0.0` as the sole primary SQL parser.
- **Rationale**:
  - Pure Python (no native build step, no wheel matrix) — matches graphify's
    cross-platform constitution requirement (macOS / Linux / Windows first-class).
  - Multi-dialect (Postgres, MySQL, SQLite, T-SQL, Oracle, BigQuery, Snowflake,
    DuckDB, Redshift) out of the box — covers all 5 dialects the spec names and
    several more at zero extra cost.
  - Statement-level iteration API: `sqlglot.parse(text, dialect=...)` returns an
    iterator of expression trees, one per top-level statement. Enables the
    streaming extraction required for SC-008 / 10k-stmt files.
  - Permissive mode: `sqlglot.parse(text, error_level=ErrorLevel.WARN)` collects
    errors without raising on partial failures — directly supports FR-012 / FR-013
    (per-statement fallback).
  - Expression tree walking API (`expression.walk()` / `find_all()`) gives direct
    access to `exp.Table`, `exp.Column`, `exp.Join`, `exp.CTE`, `exp.Insert`, etc.
    — no custom visitor infrastructure needed.
  - Active maintenance, large user base (dbt, Superset, Mode use it).
- **Alternatives considered**:
  - **`tree-sitter-sql`**: Requires a compiled grammar, adds a binary wheel per
    platform, and its node names are lower-level syntactic tokens (not
    semantic objects like `exp.Table`). Would require us to re-implement
    dialect-specific semantic unification on top of it. Rejected for Phase 1;
    listed as a future alternative in the spec.
  - **`sqlparse`**: Tokenizer, not a true parser. No expression tree. Can't
    resolve qualified names or joins reliably. Rejected.
  - **`pglast`**: Postgres-only. Rejected — breaks the multi-dialect requirement.
  - **Hand-written parser**: Massive surface area; dialect coverage would take
    years. Rejected.

---

## R-002 Parse-failure strategy

- **Decision**: Three-layer graceful degradation.
  1. Try `sqlglot.parse(text, dialect=dialect, error_level=ErrorLevel.WARN)` and
     collect per-statement errors from the returned `ParseError` objects.
  2. For any statement that `sqlglot` could not produce an expression for, run a
     narrow regex-based fallback scan (`CREATE\s+(TABLE|VIEW|MATERIALIZED VIEW)`,
     `INSERT\s+INTO\s+(\w+)`, `UPDATE\s+(\w+)`, `DELETE\s+FROM\s+(\w+)`,
     `FROM\s+([\w.]+)`) to recover best-effort `defines` / `references` edges,
     marked `confidence: "AMBIGUOUS"`.
  3. If **the entire file** fails to tokenize (binary content, Jinja templates,
     etc.), emit only a `sql_file` node with `parse_status = "failed"` and the
     parser error in attributes.
- **Rationale**: FR-012 and FR-013 mandate that failures are recoverable at
  file-level and statement-level. `sqlglot`'s `ErrorLevel.WARN` does the file-
  level heavy lifting; the regex fallback is 40 lines of code and catches the
  obvious-but-weird cases (e.g., Postgres `COPY` blocks, psql `\d` meta-commands).
- **Alternatives considered**:
  - Only use `error_level=IMMEDIATE` and fail the whole file on first error.
    Rejected — violates FR-012.
  - Build a full second parser (tree-sitter-sql) as fallback. Rejected — too
    expensive; regex covers the long tail cheaply.

---

## R-003 Node ID derivation

- **Decision**: Follow the project's existing `_make_id(*parts)` convention
  (seen in `graphify/extract.py:14`) — lowercase, non-alphanumeric → `_`, strip
  edges. Extend it for SQL:
  - `sql_file`: `_make_id("file", path)` — same scheme as other file nodes.
  - `table` / `view` / `materialized_view`:
    `_make_id(node_type, schema_name, object_name)` — e.g.
    `table_public_users`, `view_analytics_daily_revenue`. Uses qualified name so
    `public.users` and `analytics.users` are distinct.
  - `column`: `_make_id("col", schema_name, object_name, column_name)` — e.g.
    `col_public_users_email`.
  - `statement`: `_make_id("stmt", path, str(index))` — path + 0-based index
    within the file. Stable across runs because file content → same parse order.
  - `cte`: `_make_id("cte", path, str(stmt_index), cte_name)` — scoped to the
    enclosing statement (CTEs are not globally addressable per FR-019).
- **Rationale**: Keeps ID derivation consistent with how tables-in-the-code
  (Python classes, JS functions) are identified today. Makes cross-referencing
  obvious in `graph.json`. Collisions across schemas are impossible because
  schema is part of the ID.
- **Alternatives considered**:
  - SHA256 of normalized text for statement IDs. Rejected — not human-readable
    in `graph.json`, and identical statements in different files would collide
    (also a problem).
  - Statement-text hash as ID. Same issue; also, a re-formatted statement would
    change ID → breaks stability.

---

## R-004 Default schema resolution

- **Decision**: Two-pass resolution per file:
  1. **First pass**: walk all statements, record any explicit schema declarations
     (`CREATE SCHEMA x`, `SET search_path = x, ...`, `CREATE TABLE x.foo ...`).
     Record the first schema observed as the file's `default_schema`. If none,
     `default_schema = "public"`.
  2. **Second pass**: when resolving an unqualified identifier, prepend
     `default_schema` and mark the resulting node's `extraction_provenance` as
     `INFERRED` (not `EXTRACTED`) so users can audit.
- **Rationale**: Matches spec Assumption ("default_schema defaults to `public`
  unless the file declares otherwise"). Two-pass is simple and keeps each
  statement-level handler stateless. `INFERRED` marking preserves the
  audit-the-guesses invariant graphify already uses elsewhere.
- **Alternatives considered**:
  - Cross-file schema inference (propagate from `schema.sql` to
    `queries.sql`). Rejected for Phase 1 — creates order dependence between
    files, hard to make deterministic, out of spec scope.
  - Defaulting to no schema (unqualified IDs). Rejected — collapses
    `sales.users` and `analytics.users` into the same node.

---

## R-005 Identifier casing

- **Decision**: Unquoted identifiers → lowercase. Quoted identifiers (`"Users"`,
  `` `orders` ``, `[dbo]`) → preserve case as written. Apply casing rule *before*
  ID derivation.
- **Rationale**: Matches ANSI SQL semantics (PostgreSQL folds unquoted to
  lowercase; quoted is case-sensitive). Matches spec Assumption. Keeps
  `Users` and `users` collapsing correctly when both are unquoted.
- **Alternatives considered**:
  - Always lowercase. Rejected — would erroneously merge MSSQL `[UserID]` and
    `[userid]` which the DB treats as identical on default collation but keeps
    distinct on case-sensitive collation; user expects what they wrote.
  - Always preserve. Rejected — `SELECT * FROM users` and `SELECT * FROM USERS`
    in Postgres are the same table; merging them is correct.

---

## R-006 Streaming extraction for large files

- **Decision**: Use `sqlglot.parse(text, dialect=...)` which returns a
  `list[Expression | None]` (one entry per top-level statement). Process
  statements with a `for expr in parsed:` loop and **emit nodes/edges per
  statement, then drop the expression reference** so Python GC can release the
  subtree before the next statement is parsed.
- **Rationale**: Memory scales O(max_statement_size) rather than
  O(file_size). `sqlglot` is itself a single-pass tokenizer followed by
  statement-level expression building, so the in-memory cost is bounded by the
  single largest statement, not the whole file.
- **Alternatives considered**:
  - Split file on `;` manually, parse each piece with `sqlglot.parse_one`.
    Rejected — `;` inside strings/comments/DO blocks breaks naive splitting,
    and `sqlglot.parse` already handles this correctly.
  - Stream parse via a custom tokenizer. Rejected — reinventing the wheel.

---

## R-007 Integration with the existing cache

- **Decision**: No changes to `graphify/cache.py`. The cache is keyed by
  `(path, sha256)` and stores the extracted `{"nodes": [...], "edges": [...]}`
  payload. `extract_sql()` returns the same payload shape that
  `load_cached / save_cached` already expects. `.sql` files get cache hits
  automatically on unchanged content.
- **Rationale**: Minimum surface area, maximum reuse. Matches constitution
  Principle IV (cache honored across the board).
- **Alternatives considered**:
  - Separate SQL cache with parser-version key (so a `sqlglot` upgrade
    invalidates SQL but not code). Rejected for Phase 1 — premature
    optimization; the existing cache's SHA256 key already invalidates
    correctly on file change, and parser-version changes are a manual-refresh
    concern.

---

## R-008 CLI flag defaults

- **Decision**:

  | Flag                      | Default     | Effect when set                                          |
  |---------------------------|-------------|----------------------------------------------------------|
  | `--sql-dialect`           | `auto`      | Pass dialect to `sqlglot.parse(..., dialect=...)`. `auto` = dialect-agnostic (sqlglot default).  |
  | `--sql-object-level`      | `statement` | Controls graph verbosity. `file` = `sql_file` nodes only; `statement` = + statement + table/view; `column` = + columns. |
  | `--sql-lineage`           | `off`       | Phase 3 only. When on, emit `derives_from` column-level edges. |
  | `--sql-embedded`          | `off`       | Phase 3 only. When on, scan code string literals for embedded SQL. |

- **Rationale**: Defaults keep the happy path inclusive (you get tables, views,
  statements out of the box) but exclude the more-expensive / more-speculative
  features until the user opts in. Matches Principle IV (performance as
  default) and Principle III (consistent flag naming).
- **Alternatives considered**:
  - `--sql-lineage` on by default. Rejected — Phase 3 accuracy is explicitly
    best-effort; users should opt in knowingly.

---

## R-009 Report integration point

- **Decision**: Extend `graphify/report.py` with a new private helper
  `_render_sql_overview(nodes, edges) -> str | None`. It returns `None` when
  the graph contains zero SQL nodes (FR-025) — the caller simply omits the
  section. Returned markdown is inserted between the "God Nodes" and "Surprising
  Connections" blocks of `GRAPH_REPORT.md`.
- **Rationale**: Small, composable addition that matches how existing sections
  are assembled. Preserves the existing report structure for non-SQL repos.
- **Alternatives considered**:
  - New top-level file `SQL_REPORT.md`. Rejected — introduces a new output
    artifact and changes the user-visible contract (constitution Principle III
    explicitly calls out the stable artifact names).

---

## R-010 Performance validation strategy

- **Decision**: Add two benchmark cases to `graphify/benchmark.py`:
  1. `sql_corpus` — 500 synthetic `.sql` files totaling 50k statements. Measure
     full extraction wall-clock and peak RSS.
  2. `mixed_corpus_with_sql_added` — an existing non-SQL benchmark repo with a
     `.sql` file hidden under the repo root. Measure vs the same repo without
     the `.sql` file. Difference MUST be < 15% (SC-007).
- **Rationale**: Gives CI a hard threshold for the performance constitution gate.
  Catches regressions caused by accidentally re-parsing on every run, or by
  embedded-SQL detection leaking into Phase 1/2.
- **Alternatives considered**:
  - Manual-only profiling. Rejected — constitution Principle II requires tests;
    regression tests for performance invariants count.

---

## R-011 Phase 3 embedded-SQL scope (future-prep, not Phase 1/2 scope)

- **Decision**: Phase 3 targets (initial cut):
  - Python DB-API: `cursor.execute(SQL_STRING)` / `cursor.executemany(...)`.
  - SQLAlchemy: `text("SQL_STRING")`, `engine.execute(...)`.
  - Common query builder entry points by name (duck-typed): `.query(...)`,
    `.raw(...)`, `.execute(...)` — marked `INFERRED` because not every
    `execute` is SQL-related.
  - Plain string-literal detection in `.py`, `.js`, `.ts`, `.go` files with
    SQL-shaped content (starts with `SELECT`, `INSERT`, `UPDATE`, `DELETE`,
    `CREATE`, `WITH` — case-insensitive, respecting leading whitespace).
  - ORM model-class introspection: **out of scope** (Django `models.Model`,
    SQLAlchemy `declarative_base`, etc. are large surface areas).
- **Rationale**: Captures the 80/20 of embedded SQL in Python/JS/Go repos. ORM
  introspection would roughly double Phase 3 effort and most ORM-defined
  schemas are ALSO expressed as migrations (which are `.sql`) — so the
  graph is not actually missing that information.
- **Alternatives considered**:
  - Full ORM coverage in Phase 3. Rejected — scope blow-up, minimal
    incremental value for users whose schemas live in migrations anyway.
  - No embedded-SQL detection at all. Rejected — spec US3 is the stated goal
    and reserves architectural capacity from Phase 1.

---

## Summary of resolved unknowns

- Primary parser: `sqlglot >= 25.0.0` ✅
- Fallback strategy: `sqlglot` WARN mode + narrow regex + file-level error node ✅
- Node ID scheme: qualified, deterministic, follows existing `_make_id` ✅
- Default schema: two-pass; `public` fallback; INFERRED marking ✅
- Casing: lowercase unquoted, preserve quoted ✅
- Streaming: per-statement iteration + drop reference ✅
- Cache: reuse existing cache unchanged ✅
- CLI defaults: `--sql-object-level=statement`, `--sql-lineage=off`,
  `--sql-embedded=off`, `--sql-dialect=auto` ✅
- Report integration: inline `_render_sql_overview` in `report.py`,
  omit when empty ✅
- Performance gate: `sql_corpus` + `mixed_corpus_with_sql_added` benchmarks ✅
- Phase 3 embedded-SQL scope: DB-API / SQLAlchemy / heuristic literals;
  no ORM introspection ✅

**No NEEDS CLARIFICATION items remain. Planning may proceed to Phase 1.**
