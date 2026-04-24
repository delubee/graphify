# Contract: CLI flags for SQL support

**Feature**: 001-sql-native-support
**Module**: `graphify/__main__.py`
**Phase**: 1 introduces flags (with Phase-2/3 behavior gated off)

## Flags

| Flag                      | Type      | Default      | Phase introduced | Phase activated |
|---------------------------|-----------|--------------|------------------|-----------------|
| `--sql-dialect`           | choice    | `auto`       | 1                | 1               |
| `--sql-object-level`      | choice    | `statement`  | 1                | 1               |
| `--sql-lineage`           | boolean   | `off`        | 1                | 3               |
| `--sql-embedded`          | boolean   | `off`        | 1                | 3               |

All flags are registered on the top-level `graphify` command and its relevant
subcommands (`graphify .`, `graphify update .`, `graphify clone`, `graphify watch`).

## `--sql-dialect`

- **Choices**: `auto` | `postgres` | `mysql` | `sqlite` | `tsql` | `oracle` | `ansi`
- **Default**: `auto`
- **Effect**: Passed to `sqlglot.parse(..., dialect=...)`. `auto` maps to
  `dialect=None` (sqlglot's permissive multi-dialect default).
- **Validation**: Any value not in the choice list MUST produce an error of the
  form: `"error: invalid --sql-dialect value 'foo'. valid: auto, postgres, mysql, sqlite, tsql, oracle, ansi"`.
  Error message names the offending value (constitution III — actionable errors).

## `--sql-object-level`

- **Choices**: `file` | `statement` | `column`
- **Default**: `statement`
- **Effect**:
  - `file`: emit only `sql_file` nodes. No statement / table / column nodes.
    Use case: very large SQL dumps where the user wants file-level overview only.
  - `statement` (default): emit `sql_file`, `statement`, `table`, `view`,
    `materialized_view`, `cte` nodes + all edges except `has_column`.
  - `column`: all of the above + `column` nodes + `has_column` + `references`
    edges.

## `--sql-lineage`

- **Type**: boolean flag (`--sql-lineage` sets true; absence = false)
- **Default**: `off`
- **Effect (Phase 1/2)**: accepted but a no-op. If passed in Phase 1 or 2,
  graphify MUST print a one-line informational notice:
  `"[graphify] --sql-lineage requires Phase 3; currently a no-op."`
- **Effect (Phase 3)**: enables `derives_from` edge emission per SELECT projection.

## `--sql-embedded`

- **Type**: boolean flag (`--sql-embedded` sets true; absence = false)
- **Default**: `off`
- **Effect (Phase 1/2)**: accepted but a no-op; same informational notice as
  `--sql-lineage`.
- **Effect (Phase 3)**: enables string-literal scanning in `.py`/`.js`/`.ts`/`.go`
  files per R-011.

## Error contract

- Any flag combination MUST be accepted or rejected at argument-parsing time,
  not silently during extraction.
- Misspellings of choice values produce a clear error message naming valid values.
- `--help` text MUST list all four flags under a `SQL` heading.

## `graphify watch` interaction

- Watch mode inherits the same four flags from the parent invocation. Changing
  flag values requires restarting `graphify watch` (same as today for other flags).

## `graphify install` interaction

- `graphify install` does not need any SQL flags. The installed skill always
  uses Phase-1/2 defaults; Phase 3 flags are opt-in by the user at runtime.

## Backward compatibility

- None of the new flags are required. A graphify invocation with no SQL flags
  MUST behave identically to the pre-feature baseline *except* for the new
  presence of SQL nodes/edges in `graph.json` when `.sql` files exist in the
  scanned corpus.
- Scripts and CI jobs invoking `graphify .` without the new flags continue to
  work without modification.
