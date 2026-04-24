# Contract: `graphify.sql.extract_sql`

**Feature**: 001-sql-native-support
**Module**: `graphify/sql/extract_sql.py`
**Phase**: 1 (MVP)

## Signature

```python
from pathlib import Path
from typing import TypedDict, Literal

class SqlExtractionResult(TypedDict):
    nodes: list[dict]
    edges: list[dict]
    errors: list[dict]  # {"path": str, "line": int | None, "message": str}

def extract_sql(
    path: Path,
    *,
    dialect: str = "auto",
    object_level: Literal["file", "statement", "column"] = "statement",
    project_root: Path | None = None,
) -> SqlExtractionResult: ...
```

## Inputs

- `path`: absolute or project-root-relative path to a `.sql` file. MUST exist
  and MUST be readable. Caller (detect.py pipeline) guarantees these invariants.
- `dialect`: one of `"auto"`, `"postgres"`, `"mysql"`, `"sqlite"`, `"tsql"`,
  `"oracle"`, `"ansi"`. Any other value MUST raise `ValueError` with a message
  naming the offending value and listing valid dialects.
- `object_level`: graph verbosity knob per R-008. `"file"` emits only a
  `sql_file` node. `"statement"` emits file + statement + table/view/CTE
  nodes. `"column"` emits all of the above + `column` nodes.
- `project_root`: used to normalize `sql_file.path` to a project-relative path
  in the `label` / `path` fields (for consistency with other file nodes).
  If `None`, the path is used as-is.

## Output

`SqlExtractionResult` with:

- `nodes`: list of node dicts conforming to the shapes defined in
  `data-model.md` (at minimum one `sql_file` node).
- `edges`: list of edge dicts.
- `errors`: list of parser error records. Empty when `parse_status == "ok"`.

## Behavior

### Happy path (file parses cleanly)

1. Read file bytes, compute SHA256, decode as UTF-8 (errors=`replace`).
2. Call `sqlglot.parse(text, dialect=dialect_arg, error_level=ErrorLevel.WARN)`
   where `dialect_arg = None` if `dialect == "auto"`.
3. For each parsed expression (one per top-level statement):
   - Determine `statement_type` from the expression class (`exp.Create`,
     `exp.Select`, `exp.Insert`, `exp.Update`, `exp.Delete`, `exp.With`, etc.).
   - Emit a `statement` node with `line_start`, `line_end`, `text_snippet`.
   - Walk the expression tree for tables/views/columns/CTEs:
     - `exp.Table` → emit `table`/`view`/`materialized_view` node (de-dup by
       ID) + edge from statement to the entity (`selects_from` / `joins` /
       `inserts_into` / `updates` / `deletes_from` based on statement type).
     - `exp.Column` (only at `object_level="column"`) → emit `column` node +
       `has_column` edge.
     - `exp.CTE` → emit `cte` node + `uses_cte` edge.
   - For `CREATE TABLE / VIEW / MATERIALIZED VIEW`: emit the defined entity +
     `defines` edge from file + `has_column` edges for declared columns.
   - For `CREATE VIEW / MATERIALIZED VIEW AS SELECT ...`: emit `depends_on`
     edges from the view to every table/view referenced in the SELECT.
4. Set `sql_file.parse_status = "ok"`.

### Degraded path — per-statement failure

For any statement where `sqlglot.parse` returned `None` (couldn't parse) or
raised during expression walk:

1. Emit a `statement` node with `parse_status = "failed"` and the error
   message in an `error` attribute (non-spec, diagnostic).
2. Run the narrow regex fallback on the statement text to recover obvious
   object definitions (CREATE TABLE, INSERT INTO, etc.). Emit recovered
   nodes/edges with `confidence = "AMBIGUOUS"`.
3. Record the error in `result["errors"]`.
4. Continue with the next statement.

### Degraded path — whole-file failure

If `sqlglot.parse(text)` itself raises (`sqlglot.errors.TokenError` or
similar), or if the file is binary / empty / only whitespace:

1. Run the regex fallback on the whole file text. Emit any recovered
   `table` / `view` / `depends_on` nodes/edges with `confidence = "AMBIGUOUS"`.
2. Emit a single `sql_file` node with `parse_status = "failed"` and the
   parser error message.
3. Return `SqlExtractionResult` with the fallback nodes (if any) and a
   populated `errors` list.

### Never-raise invariant

`extract_sql()` MUST NOT raise except for:
- `FileNotFoundError` (bug in the caller).
- `ValueError` on invalid `dialect` argument (contract violation).

All other failure modes are captured in `errors` and reflected in
`parse_status`. This supports FR-030 ("no SQL-related failure may corrupt the
non-SQL portion of the graph").

## Determinism contract

- Given identical file bytes and identical arguments, `extract_sql()` MUST
  return byte-identical `nodes` + `edges` lists (same order, same IDs, same
  attributes).
- Iteration order over `sqlglot` expression tree MUST be stable (sqlglot's
  `walk()` is deterministic; list-building code MUST NOT use `set()` where
  order matters).

## Integration contract

- Caller (`graphify/extract.py` dispatcher) passes one `.sql` file at a time.
- Caller is responsible for the SHA256 cache: cache key is
  `(path, sha256, "extract_sql_v1")`. If a cache hit is found, `extract_sql()`
  is not called. This mirrors how code extraction is cached today.
- Cache version suffix (`_v1`) lets us invalidate SQL caches independently if
  the extraction logic changes in a future version. Initial value `_v1`;
  bump on any change to emitted node/edge shape.

## Not in scope

- Connecting to a database for schema metadata. Static analysis only.
- Executing the SQL.
- Formatting or linting output.
- Resolving cross-file schema context beyond the default-schema rule in R-004.

## Test fixtures that exercise this contract

- `tests/fixtures/sql/schema.sql` — CREATE TABLE with various column types +
  foreign keys.
- `tests/fixtures/sql/views.sql` — CREATE VIEW + CREATE MATERIALIZED VIEW
  referencing schema.sql tables.
- `tests/fixtures/sql/queries.sql` — SELECT, JOIN, WITH/CTE, nested subquery.
- `tests/fixtures/sql/migrations/001_init.sql` — mixed DDL/DML.
- `tests/fixtures/sql/multi_schema.sql` — `SET search_path`, cross-schema
  references (`sales.users` vs `analytics.users`).
- `tests/fixtures/sql/malformed.sql` — one valid statement, one malformed, one
  Postgres-specific that requires fallback.
- `tests/fixtures/sql/empty.sql` — zero bytes.
- `tests/fixtures/sql/giant.sql` — generated in `conftest.py` with 1000+
  statements for streaming / memory tests.
