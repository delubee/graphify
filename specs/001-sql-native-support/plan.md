# Implementation Plan: Powerful SQL Native Support

**Branch**: `001-sql-native-support` | **Date**: 2026-04-24 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/001-sql-native-support/spec.md`

## Summary

Promote `.sql` from a near-unsupported file type into a first-class knowledge source in
graphify. Extend detection, extraction, analysis, and reporting so `.sql` files produce
structured nodes (files, statements, tables, views, columns, CTEs) and edges
(`selects_from`, `joins`, `inserts_into`, `updates`, `deletes_from`, `defines`,
`depends_on`, `has_column`, `uses_cte`, `derives_from`) in the knowledge graph.

Technical approach: add a new `FileType.SQL` category in `detect.py` and a dedicated
`extract_sql()` function in a new `graphify/sql/` subpackage. Use **`sqlglot`** as the
primary parser (pure-Python, multi-dialect, statement-level iteration, permissive parse
mode for dialect-agnostic fallback). A lightweight regex-based fallback recovers
`sql_file` nodes + best-effort object mentions when `sqlglot` raises on a whole file.
Reuse the existing SHA256 cache, `.graphifyignore`, watch loop, and shrink-guard machinery
untouched. Phase 1 ships detection + structural extraction (MVP, US1). Phase 2 extends
`analyze.py` and `report.py` with SQL insights (US2). Phase 3 adds embedded-SQL detection
in code literals and column-level lineage (US3), gated behind `--sql-embedded` and
`--sql-lineage` CLI flags that default to `off`.

## Technical Context

**Language/Version**: Python 3.10+ (project baseline per constitution; also per
`pyproject.toml`: `requires-python = ">=3.10,<3.14"`).
**Primary Dependencies**:
- Existing: `networkx`, `tree-sitter` family, `pathlib`, stdlib.
- **New (core)**: `sqlglot >= 25.0.0` — pure Python, no compiled wheel, multi-dialect
  (Postgres / MySQL / SQLite / T-SQL / Oracle / ANSI), statement-level iteration API
  (`sqlglot.parse`), expression-tree traversal (`exp.walk`).
- **New (no-op for Phase 1/2)**: none. Phase 3 embedded-SQL detection leverages the
  already-present tree-sitter grammars (`tree_sitter_python`, `tree_sitter_javascript`,
  etc.) to locate string literals; no new parser is added for Phase 3.

**Storage**: Filesystem only. Output artifacts `graphify-out/graph.json`,
`graph.html`, `GRAPH_REPORT.md`, `cache/*.json` — same locations as today. No database
connection, no remote calls.

**Testing**: `pytest` with real filesystem via `tmp_path`. New test files:
- `tests/test_sql_detect.py` — detection + `.graphifyignore` rules.
- `tests/test_sql_extract.py` — statement-type coverage + multi-statement + malformed
  fallback + ID stability.
- `tests/test_sql_report.py` — GRAPH_REPORT.md SQL Overview section (Phase 2).
- `tests/test_sql_pipeline.py` — end-to-end: `detect → extract → build → report`.
- Fixtures: `tests/fixtures/sql/schema.sql`, `views.sql`, `queries.sql`,
  `migrations/001_init.sql`, `malformed.sql`, `empty.sql`, `giant.sql`
  (1000+ stmt synthetic), `multi_schema.sql`.

**Target Platform**: macOS / Linux / Windows. `sqlglot` is pure Python, so no platform
quirks expected. Filesystem paths handled via `pathlib.Path` as in the rest of the
codebase.

**Project Type**: Single-project Python library + CLI (matches the existing `graphify/`
layout). No frontend / backend split.

**Performance Goals**:
- Phase 1 on a 10k-statement SQL corpus: full extraction in < 5 s wall-clock on a
  modern laptop.
- Per-file incremental path: cache hit < 5 ms per unchanged file (same as today's
  non-SQL cache).
- Watch-mode re-extraction of a single changed `.sql` file: < 500 ms end-to-end.

**Constraints**:
- Performance (constitution IV): adding SQL support MUST NOT slow down a non-SQL
  corpus by more than 15% wall-clock; detection fast-path checks an extension set.
- Memory (SC-008 + constitution IV): `sqlglot.parse_one(...)` per statement via the
  `sqlglot.parse(text)` streaming iterator — never materialize the full AST of the
  whole file.
- No live DB access (spec Assumption): zero network I/O during extraction; unit tests
  MUST not require network.
- Graceful degradation (FR-012/013/014): per-file and per-statement try/except
  boundaries. Whole-file parser failure → regex fallback → `sql_file` node with
  `parse_status = "failed"` or `"partial"`.

**Scale/Scope**:
- Real-world upper bound: a repo like `postgres/postgres` has ~2000 `.sql` test files
  totaling ~500k statements. Within-test boundary; larger users should downgrade via
  `--sql-object-level=file` or `.graphifyignore`.
- Node-count sanity: `O(N + tables + columns)` where N = statement count. For 10k
  statements with ~200 tables and ~2000 columns: ~12k SQL-related nodes.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Evaluated against `.specify/memory/constitution.md` v1.0.0. Pre-design pass:

### I. Code Quality — ✅ PASS

- New code lives in a clearly-scoped `graphify/sql/` subpackage with a single public
  entry point (`extract_sql`) — avoids sprawl in `extract.py`.
- All new public functions get type hints. A `SqlExtractionResult` TypedDict (or
  dataclass) formalizes the return shape.
- `sqlglot` is the only new third-party dependency; justified in PR description
  (pure-Python, multi-dialect, active maintenance, only viable Python-native option
  covering all 5 required dialects).
- No speculative abstractions: we do **not** build a generic "parser plugin registry"
  — SQL gets its own extractor, code stays with tree-sitter.

### II. Testing Standards (NON-NEGOTIABLE) — ✅ PASS

- Unit tests for the pure SQL-to-graph mapping (given expression tree → expected
  nodes/edges), zero I/O.
- Integration tests for detection → extract → graph.json using `tmp_path`.
- All fixtures are checked in, deterministic, zero network.
- Fallback path has its own test (FR-012/013 — `malformed.sql` fixture).
- Regression tests for stable IDs (re-run produces identical node IDs) and shrink-
  guard invariant.

### III. User Experience Consistency — ✅ PASS

- New CLI flags follow the existing naming (`--sql-dialect`, `--sql-lineage`,
  `--sql-embedded`, `--sql-object-level`) — all use the `--<domain>-<option>`
  convention. No reinvention.
- Output artifact contract is preserved: the same `graph.json` /
  `GRAPH_REPORT.md` / `graph.html` — new content is additive.
- Error messages on malformed SQL will name the file + line + parser message, per
  the "actionable errors" rule.
- Logging behavior is centralized (reuse existing `print(...)` / warning style in
  `detect.py` / `extract.py`).

### IV. Performance Requirements — ✅ PASS (with a watch-item)

- SHA256 cache honored: SQL files participate in the same cache/invalidation path as
  code files. Confirmed by `tests/test_sql_cache.py` (to add).
- Benchmarks: add `sql_corpus` case to `graphify/benchmark.py` so regressions are
  caught by CI.
- Bounded concurrency: SQL extraction is synchronous per file (no fan-out per
  statement). Full-corpus parallelism continues to go through the existing
  bounded thread pool if any.
- `graphify-out/` exclusion invariant: unchanged — `.sql` files living under
  `graphify-out/` will not be picked up because `detect.py` already excludes that
  directory for *every* file type.
- **Watch item**: `sqlglot` is pure Python and can be slow on pathological inputs
  (very deep nested queries). Phase 0 research MUST benchmark on `giant.sql` and
  confirm the 15% non-SQL regression budget.

**Verdict (pre-design)**: No violations. Planning proceeds.

**Re-evaluation post-Phase-1 design**: No change. The four principles remain ✅ PASS:

- I. Code Quality — confirmed by the `graphify/sql/` subpackage layout + typed
  `SqlExtractionResult` contract in `contracts/extract_sql.md`.
- II. Testing — confirmed by the fixture list + per-statement-type coverage in
  `plan.md` → Testing, plus the never-raise invariant in `contracts/extract_sql.md`.
- III. UX — confirmed by `contracts/cli_flags.md` (reuses existing flag vocabulary;
  informational Phase-1/2 no-op notices for `--sql-lineage` / `--sql-embedded`)
  and `contracts/report_section.md` (omit-on-empty rule).
- IV. Performance — confirmed by R-007 (cache reuse) and R-010 (benchmark gate).

## Project Structure

### Documentation (this feature)

```text
specs/001-sql-native-support/
├── spec.md               ✅ Feature specification (done)
├── plan.md               ✅ This file
├── research.md           ➜  Phase 0 output
├── data-model.md         ➜  Phase 1 output
├── quickstart.md         ➜  Phase 1 output
├── contracts/            ➜  Phase 1 output
│   ├── extract_sql.md    ➜  extractor contract
│   ├── cli_flags.md      ➜  CLI flag contract
│   └── report_section.md ➜  GRAPH_REPORT.md "SQL Overview" contract
├── checklists/
│   └── requirements.md   ✅ Specification quality checklist (done)
└── tasks.md              ➜  Phase 2 output (/speckit.tasks command)
```

### Source Code (repository root)

```text
graphify/
├── __init__.py
├── __main__.py                # CLI entry — add --sql-dialect etc.
├── detect.py                  # + SQL_EXTENSIONS, FileType.SQL
├── extract.py                 # dispatch .sql → graphify.sql.extract_sql
├── watch.py                   # + SQL_EXTENSIONS in _WATCHED_EXTENSIONS
├── analyze.py                 # (Phase 2) SQL-aware hotspot helpers
├── report.py                  # (Phase 2) SQL Overview section renderer
├── cache.py                   # unchanged (SHA256 cache covers .sql for free)
├── build.py                   # unchanged (consumes generic nodes/edges)
├── export.py                  # unchanged
└── sql/                       # NEW subpackage
    ├── __init__.py            # re-exports extract_sql
    ├── extract_sql.py         # primary sqlglot-based extractor
    ├── identifiers.py         # qualified-name normalization, stable ID derivation
    ├── fallback.py            # regex-based weak extractor for parse failures
    ├── model.py               # TypedDicts / dataclasses for node & edge shapes
    ├── statements.py          # per-statement-type handlers (CREATE TABLE, SELECT, ...)
    └── embedded.py            # (Phase 3) embedded-SQL detection in code literals

tests/
├── test_sql_detect.py         # .sql detection + .graphifyignore
├── test_sql_extract.py        # per-statement-type extraction + fallback + ID stability
├── test_sql_report.py         # (Phase 2) SQL Overview section
├── test_sql_pipeline.py       # end-to-end detect→extract→build→report
└── fixtures/
    └── sql/
        ├── schema.sql
        ├── views.sql
        ├── queries.sql
        ├── multi_schema.sql
        ├── malformed.sql
        ├── empty.sql
        ├── giant.sql          # synthetic 1000+ statements (generated in conftest)
        └── migrations/
            └── 001_init.sql
```

**Structure Decision**: Single-project Python library layout (Option 1 in the template).
SQL parsing is isolated in a new `graphify/sql/` subpackage rather than inlined in
`extract.py`, because (a) the SQL data model is table/query-oriented rather than
class/function-oriented and reusing the tree-sitter dispatcher would require
awkward shimming, (b) it keeps `extract.py`'s 2000-line tree-sitter file focused,
and (c) it gives Phase 3 (`embedded.py`) a natural home without further ballooning
the top-level package.

## Complexity Tracking

*No constitutional violations. Nothing to justify here at this stage.*

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| *(none)*  | —          | —                                   |

### Watch-items (not violations, but to revisit post-implementation)

- If `sqlglot` parse time on `giant.sql` exceeds the 15% non-SQL-corpus-overhead
  ceiling, add an escape hatch: `--sql-object-level=file` short-circuits to the
  regex fallback and produces `sql_file` nodes only. Already in the CLI design;
  this is noting when we'd reach for it.
- If embedded-SQL detection in Phase 3 adds >10% to Python extraction time, gate it
  even more strictly (opt-in per-language via `--sql-embedded=python` vs the default
  `off`).
