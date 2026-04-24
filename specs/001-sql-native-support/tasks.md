# Tasks: Powerful SQL Native Support

**Input**: Design documents from `/specs/001-sql-native-support/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

**Tests**: Tests are **INCLUDED** because (a) the spec has a dedicated "Testing Expectations"
section enumerating required test files and fixtures, and (b) the constitution
principle **II. Testing Standards (NON-NEGOTIABLE)** forbids merging correctness-critical
behavior without tests. Test tasks therefore precede their implementation counterparts in
each user-story phase.

**Organization**: Tasks are grouped by user story so each story can be implemented,
tested, and deployed independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task serves (US1, US2, US3)
- File paths are absolute within the repo root.

## Path Conventions

Single-project Python library + CLI — source in `graphify/`, tests in `tests/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Dependency + fixture scaffolding that everything else builds on.

- [X] T001 Add `sqlglot>=25.0.0` to `[project] dependencies` in `pyproject.toml` (justify in the PR description per constitution I: pure-Python, multi-dialect, no binary wheel)
- [X] T002 [P] Create SQL fixture files: `tests/fixtures/sql/schema.sql`, `tests/fixtures/sql/views.sql`, `tests/fixtures/sql/queries.sql`, `tests/fixtures/sql/migrations/001_init.sql`, `tests/fixtures/sql/malformed.sql`, `tests/fixtures/sql/empty.sql`, `tests/fixtures/sql/multi_schema.sql` — each seeded from the quickstart.md examples
- [X] T003 [P] Add a `giant_sql` fixture generator function in `tests/conftest.py` that synthesizes a ≥1000-statement `.sql` file into `tmp_path` (used by streaming / memory tests)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core shared infrastructure that every user-story phase depends on — detection must recognize `.sql`, the subpackage must exist, and the shared identifier/model helpers must be in place before any extractor work can begin.

**⚠️ CRITICAL**: No user-story work can start until this phase is complete.

- [X] T004 Create the `graphify/sql/` subpackage with `__init__.py` re-exporting `extract_sql`, and empty placeholder modules `graphify/sql/extract_sql.py`, `graphify/sql/identifiers.py`, `graphify/sql/fallback.py`, `graphify/sql/model.py`, `graphify/sql/statements.py`, `graphify/sql/embedded.py`
- [X] T005 [P] Define the shared data-model TypedDicts (`SqlExtractionResult`, node-shape helpers) in `graphify/sql/model.py` per `specs/001-sql-native-support/data-model.md`
- [X] T006 [P] Implement identifier helpers in `graphify/sql/identifiers.py`: `_make_sql_id(...)` following the existing `_make_id` convention, `normalize_identifier(raw, quoted)` (R-005 casing), `resolve_default_schema(statements) -> str` (R-004 two-pass), `qualify(schema, object)`, `qualify_column(schema, object, column)`
- [X] T007 Add `FileType.SQL = "sql"` and `SQL_EXTENSIONS = {'.sql'}` constants in `graphify/detect.py`; add a `detect()` bucket key for SQL files
- [X] T008 Wire `.sql` files through the detect pipeline: update `graphify/detect.py` so `SQL_EXTENSIONS` files land in the new `sql` bucket, respecting `.graphifyignore` and the existing `graphify-out/` exclusion (T007 prerequisite)
- [X] T009 [P] Extend `_WATCHED_EXTENSIONS` in `graphify/watch.py` to include `SQL_EXTENSIONS` so watch mode triggers on `.sql` changes

**Checkpoint**: Detection recognizes `.sql`, the `graphify/sql/` subpackage exists with its type model and identifier utilities, and watch mode observes SQL files. User-story phases can now proceed in parallel.

---

## Phase 3: User Story 1 - Scan a SQL-Heavy Repository and See Real Structure (Priority: P1) 🎯 MVP

**Goal**: `graphify .` on a repo with `.sql` files produces a graph containing file, statement, table, view, materialized_view, column, and CTE nodes with the full edge set defined in `contracts/extract_sql.md`. Malformed files degrade gracefully. Watch + cache + `.graphifyignore` all work with `.sql`.

**Independent Test**: Run `graphify .` on the fixture repo from `quickstart.md`. Assert the expected nodes/edges per the Phase 1 section of `quickstart.md` (tables `public.users` / `public.orders` / `public.good_one`, view `public.active_users` with `depends_on`, CTE `recent_orders`, `parse_status = "partial"` on `002_broken.sql`).

### Tests for User Story 1 (write first, ensure they FAIL before implementation) ⚠️

> Constitution II: tests before implementation. These MUST exist and be red before T016–T023 land.

- [X] T010 [P] [US1] Write `tests/test_sql_detect.py`: assert `.sql` files are enumerated by `detect()`, assert `.graphifyignore` rules exclude them correctly, assert `graphify-out/*.sql` is always skipped
- [X] T011 [P] [US1] Write `tests/test_sql_extract.py`: per-statement-type tests covering CREATE TABLE, ALTER TABLE, CREATE VIEW, CREATE MATERIALIZED VIEW, SELECT (with + without JOIN), INSERT, UPDATE, DELETE, multi-statement file, WITH/CTE (including chained CTEs), foreign-key `REFERENCES`, unqualified-reference default-schema resolution, `parse_status` partial/failed cases, ID stability across re-runs
- [X] T012 [P] [US1] Write `tests/test_sql_pipeline.py`: end-to-end detect → extract → build → export on the `tests/fixtures/sql/` tree; assert `graph.json` contents match the Phase 1 expectations from `specs/001-sql-native-support/quickstart.md`
- [X] T013 [P] [US1] Write `tests/test_sql_shrink_guard.py`: regression test that `extract_sql` failing for every file does not shrink `graph.json` vs a prior successful run (constitution IV invariant)

### Implementation for User Story 1

- [X] T014 [P] [US1] Implement the regex-based weak extractor in `graphify/sql/fallback.py` covering `CREATE\s+(TABLE|VIEW|MATERIALIZED VIEW)`, `INSERT\s+INTO`, `UPDATE`, `DELETE\s+FROM`, `FROM\s+<qualified>`; every recovered node/edge tagged `confidence="AMBIGUOUS"` per R-002
- [X] T015 [P] [US1] Implement per-statement-type handlers in `graphify/sql/statements.py`: one function per statement type (`handle_create_table`, `handle_create_view`, `handle_create_materialized_view`, `handle_alter_table`, `handle_select`, `handle_insert`, `handle_update`, `handle_delete`, `handle_with`) each emitting the node/edge shapes from `specs/001-sql-native-support/data-model.md`
- [X] T016 [US1] Implement the `extract_sql()` entry point in `graphify/sql/extract_sql.py` matching `contracts/extract_sql.md`: file read → SHA256 → `sqlglot.parse(..., error_level=WARN)` → per-statement dispatch to `statements.py` → fallback via `fallback.py` on whole-file failure → assemble `SqlExtractionResult`; respect the `object_level` knob; never raise except `FileNotFoundError` / `ValueError(invalid dialect)` (depends on T005, T006, T014, T015)
- [X] T017 [US1] Wire SQL dispatch into `graphify/extract.py`: when a file's extension is `.sql`, route to `graphify.sql.extract_sql.extract_sql()` instead of the tree-sitter dispatcher; merge returned nodes/edges into the result payload that `build.py` already consumes (depends on T016)
- [X] T018 [US1] Add `--sql-dialect` (choices: auto/postgres/mysql/sqlite/tsql/oracle/ansi, default `auto`) and `--sql-object-level` (choices: file/statement/column, default `statement`) to `graphify/__main__.py`; thread them through to `extract_sql()` via the detect→extract call site; invalid values produce the actionable error message specified in `contracts/cli_flags.md`
- [X] T019 [US1] Add `--sql-lineage` and `--sql-embedded` boolean flags to `graphify/__main__.py` (Phase-3 flags); in Phase 1 they MUST print the informational no-op notice from `contracts/cli_flags.md` and not activate any Phase-3 behavior
- [X] T020 [US1] Verify SHA256 cache integration end-to-end: modify `.sql` file, re-run `graphify`, assert only that file is re-extracted (cache hit on others). No new code expected — this is a test-only verification via `tests/test_sql_pipeline.py::test_incremental_cache` (depends on T017)
- [X] T021 [US1] Add a rebuild path for `.sql` files in `graphify/watch.py`: extend `_rebuild_code()` or sibling helper to call `extract_sql` for changed `.sql` files on file-change events (depends on T009, T017)
- [X] T022 [US1] Add `FileType.SQL` handling to `graphify/export.py` only if export emits file-type-specific labels; otherwise no-op (quick audit — may be zero code)
- [X] T023 [US1] Add `SqlExtractionResult` and the `extract_sql` symbol to `graphify/__init__.py` public re-exports so `build_merge()` users can call it directly if needed (depends on T016)

**Checkpoint**: US1 is fully functional. A user can run `graphify .` on a `.sql`-bearing repo and see file / statement / table / view / materialized_view / column / cte nodes with the full Phase-1 edge set. Malformed files degrade. Watch + cache + `.graphifyignore` all work. The full Phase 1 section of `quickstart.md` passes. Tests T010–T013 are green.

---

## Phase 4: User Story 2 - SQL-Specific Insights in the Audit Report (Priority: P2)

**Goal**: `GRAPH_REPORT.md` gains a "SQL Overview" section with populated rankings (most-referenced tables, most-mutated tables, views by dependency fan-in, SQL hotspot files) + SQL-flavored suggested questions. Zero-SQL repos see no stub.

**Independent Test**: Run `graphify .` on the fixture repo; open `graphify-out/GRAPH_REPORT.md`; confirm the SQL Overview section's structure matches `contracts/report_section.md` with `public.users` / `public.orders` in the top rows. Then run on an empty (`.sql`-free) repo and confirm the section is absent.

### Tests for User Story 2 (write first) ⚠️

- [X] T024 [P] [US2] Write `tests/test_sql_report.py`: against a fixture graph with known counts, assert (a) `## SQL Overview` section present, (b) top-10 most-referenced tables in the documented order, (c) most-mutated rankings correct, (d) views-by-fan-in ordering correct, (e) ≥ 3 SQL-flavored suggested questions, (f) empty-repo case → no `## SQL Overview` heading anywhere, (g) 1000-table corpus produces ≤ 10 rows per table with "and N more" footnote
- [X] T025 [P] [US2] Write `tests/test_sql_analyze.py`: assert SQL nodes participate in `god_nodes()` and `surprising_connections()` on the same footing as code nodes

### Implementation for User Story 2

- [X] T026 [P] [US2] Extend `graphify/analyze.py`: update `god_nodes()`, `score_all()` (and any other ranking / hotspot helpers) to include SQL entity types in their candidate set (no special-casing; treat them uniformly)
- [X] T027 [US2] Implement the private helper `_render_sql_overview(nodes, edges) -> str | None` in `graphify/report.py` matching `contracts/report_section.md` exactly: returns `None` on zero SQL nodes (omit-on-empty rule FR-025); otherwise returns the markdown block with the four subsections
- [X] T028 [US2] Invoke `_render_sql_overview(...)` from `generate()` in `graphify/report.py` between the "God Nodes" and "Surprising Connections" blocks; append the returned string only when not `None` (depends on T027)
- [X] T029 [US2] Extend `suggest_questions()` in `graphify/analyze.py` to append ≥ 3 SQL-flavored questions when SQL nodes exist in the graph; append none when they don't (depends on T026)

**Checkpoint**: US2 is fully functional on top of US1. Users running `graphify .` on a SQL-bearing repo see the SQL Overview section; users on non-SQL repos see no change to their report. Tests T024–T025 are green. The Phase 2 section of `quickstart.md` passes.

---

## Phase 5: User Story 3 - Embedded SQL and Column-Level Lineage (Priority: P3)

**Goal**: With `--sql-embedded` enabled, code functions that issue SQL via string literals, DB-API execute, or SQLAlchemy `text()` get linked via `executes` edges to synthesized statement nodes. With `--sql-lineage` enabled, SELECT output columns carry `derives_from` edges back to their source columns.

**Independent Test**: Run `graphify . --sql-embedded --sql-lineage` on the fixture repo that includes `app.py` (Python) + `revenue.sql` (view with named projection). Confirm the `executes` edge, the `selects_from` chain, and the `derives_from` edges specified in the Phase 3 section of `quickstart.md`. Then re-run without flags and confirm the new edges/nodes are absent (opt-in gate).

### Tests for User Story 3 (write first) ⚠️

- [X] T030 [P] [US3] Write `tests/test_sql_embedded.py`: assert (a) DB-API `cursor.execute("SELECT ...")` → synthesized `statement` + `executes` edge from the surrounding function node, (b) SQLAlchemy `text("...")` → same, (c) heuristic string-literal SQL detection (SELECT / INSERT / UPDATE / DELETE / CREATE / WITH case-insensitive), (d) ORM model-class introspection is NOT performed (out of R-011 scope), (e) embedded SQL that fails to parse produces an `AMBIGUOUS`-marked record and does not drop the code function node (FR-015)
- [X] T031 [P] [US3] Write `tests/test_sql_lineage.py`: assert `derives_from` edges from output columns back to source columns for (a) simple projection `SELECT a.id FROM a`, (b) join projection `SELECT a.id, b.name FROM a JOIN b`, (c) CTE projection, (d) UNION → source columns marked `AMBIGUOUS`

### Implementation for User Story 3

- [X] T032 [P] [US3] Implement column-level lineage in `graphify/sql/extract_sql.py`: when `lineage=True`, walk SELECT expressions and emit `derives_from` edges from each output column to each source column it references; mark `AMBIGUOUS` on UNIONs / recursive CTEs per `data-model.md` (depends on T015, T016)
- [X] T033 [P] [US3] Populate `sql_function` / `sql_procedure` nodes in `graphify/sql/statements.py` by adding `handle_create_function` and `handle_create_procedure` per `data-model.md` reserved types (depends on T015)
- [X] T034 [US3] Implement `graphify/sql/embedded.py`: scan tree-sitter ASTs for `.py`/`.js`/`.ts`/`.go` files for string literals that match SQL-shape heuristic OR appear in known execute-call patterns (DB-API `cursor.execute`, `cursor.executemany`, SQLAlchemy `text()`, duck-typed `.query(...)` / `.raw(...)` per R-011); emit synthesized `statement` nodes + `executes` edges back to the enclosing function
- [X] T035 [US3] Activate `--sql-embedded` behavior in `graphify/__main__.py` and call site: when flag is true, invoke `graphify.sql.embedded.detect_embedded(...)` as part of the extract phase for code files (depends on T019, T034)
- [X] T036 [US3] Activate `--sql-lineage` behavior: pass `lineage=True` through to `extract_sql()` when flag is set; also pass it through to the embedded-SQL synthesized statements so their lineage is computed identically (depends on T019, T032, T034)
- [X] T037 [US3] Remove or update the Phase-1/2 no-op notices from T019 now that the flags have behavior (in `graphify/__main__.py`)

**Checkpoint**: All three user stories are fully functional. The complete `quickstart.md` (Phases 1, 2, 3, plus watch-mode and performance sections) passes end-to-end.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Enforce performance gates, ship benchmarks, update user-facing docs.

- [X] T038 [P] Add benchmark cases to `graphify/benchmark.py`: `sql_corpus` (500 synthetic `.sql` files, 50k statements) and `mixed_corpus_with_sql_added` (existing non-SQL corpus vs the same + one `.sql` file); measure wall-clock + peak RSS per R-010
- [X] T039 [P] Add `tests/test_sql_benchmark.py` enforcing SC-007: `mixed_corpus_with_sql_added` wall-clock ≤ `baseline × 1.15` as a CI gate per constitution IV (depends on T038)
- [X] T040 [P] Add `CHANGELOG.md` entry for the feature (user-visible behavior change per constitution III — release policy)
- [X] T041 [P] Add the feature to the `## What's new` block of `README.md` (constitution III — release policy)
- [X] T042 [P] If any runtime-guidance changes are warranted (e.g., "graphify now indexes .sql"), update `AGENTS.md`; otherwise skip
- [X] T043 Run the full `specs/001-sql-native-support/quickstart.md` walkthrough manually and verify every assertion; update `quickstart.md` if any step needs tightening (depends on T037, T039)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup, T001–T003)**: no prior dependencies; can start immediately.
- **Phase 2 (Foundational, T004–T009)**: depends on Phase 1. **BLOCKS ALL USER STORIES.**
- **Phase 3 (US1, T010–T023)**: depends on Phase 2. MVP.
- **Phase 4 (US2, T024–T029)**: depends on Phase 3 (consumes the node/edge shapes US1 produces).
- **Phase 5 (US3, T030–T037)**: depends on Phase 3 (extends `extract_sql` and adds embedded scanning). Can proceed in parallel with Phase 4 once Phase 3 is complete.
- **Phase 6 (Polish, T038–T043)**: depends on the last user story you intend to ship (Phase 3 minimum for MVP; Phase 5 for full release).

### User Story Dependencies

- **US1 (P1)**: Depends only on Foundational phase. Self-contained MVP.
- **US2 (P2)**: Depends on US1 (analyze + report consume the SQL node/edge model US1 produces). Cannot be demoed before US1 lands.
- **US3 (P3)**: Depends on US1 (reuses `extract_sql` core). Independent of US2 (lineage and report are unrelated).

### Task-level dependencies (within phases)

- T008 depends on T007.
- T016 depends on T005, T006, T014, T015.
- T017 depends on T016.
- T020 depends on T017.
- T021 depends on T009, T017.
- T023 depends on T016.
- T028 depends on T027.
- T029 depends on T026.
- T032 depends on T015, T016.
- T033 depends on T015.
- T035 depends on T019, T034.
- T036 depends on T019, T032, T034.
- T037 depends on T019.
- T039 depends on T038.
- T043 depends on T037, T039.

### Parallel Opportunities

- **Setup**: T002 + T003 in parallel (different files).
- **Foundational**: T005 + T006 + T009 in parallel (T005/T006 are leaves; T009 only touches `watch.py`). T007 must precede T008.
- **US1 tests**: T010 + T011 + T012 + T013 all parallelizable.
- **US1 implementation leaves**: T014 + T015 in parallel (separate modules).
- **US2 tests**: T024 + T025 parallel.
- **US2 implementation leaves**: T026 parallel with T024/T025 only if tests don't import analyze/report; otherwise T026 precedes T025.
- **US3 tests**: T030 + T031 parallel.
- **US3 implementation leaves**: T032 + T033 parallel with T034 (different files).
- **Polish**: T038 + T040 + T041 + T042 all parallelizable.

---

## Parallel Example: User Story 1

```bash
# Launch all US1 test tasks together (tests before implementation — constitution II):
Task: "T010 [P] [US1] Write tests/test_sql_detect.py"
Task: "T011 [P] [US1] Write tests/test_sql_extract.py"
Task: "T012 [P] [US1] Write tests/test_sql_pipeline.py"
Task: "T013 [P] [US1] Write tests/test_sql_shrink_guard.py"

# Then launch the parallelizable implementation leaves:
Task: "T014 [P] [US1] Implement regex fallback in graphify/sql/fallback.py"
Task: "T015 [P] [US1] Implement statement handlers in graphify/sql/statements.py"

# Then converge on the integration tasks (T016 → T017 → T020/T021/T023 sequentially).
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Complete Phase 1: Setup (T001–T003).
2. Complete Phase 2: Foundational (T004–T009) — **CRITICAL, blocks everything**.
3. Complete Phase 3: User Story 1 (T010–T023) — tests first, then implementation.
4. **STOP and VALIDATE**: run the Phase 1 section of `quickstart.md` end-to-end. If it passes, you have an MVP.
5. Optionally ship at this checkpoint — US1 alone already delivers the headline user value ("graphify now understands `.sql`").

### Incremental Delivery

1. Ship **Phase 1 + 2 + 3** → MVP (US1). Release as `v0.6.0-sql-mvp` or similar.
2. Ship **+ Phase 4** → SQL Overview report (US2). Release as `v0.6.0`.
3. Ship **+ Phase 5** → embedded SQL + column lineage (US3). Release as `v0.7.0`.
4. Ship **+ Phase 6** → benchmarks, docs, performance-gate CI (Polish).

### Parallel Team Strategy

With multiple developers after Foundational lands:

- **Developer A**: US1 implementation (T014–T023).
- **Developer B**: US1 tests (T010–T013) + US2 tests (T024–T025) — tests can be written against the contracts in parallel with the implementation.
- **Developer C**: Once US1 merges, picks up US2 implementation (T026–T029). Once US1 also merges, picks up US3 (T030–T037) in parallel with any US2 remainder.

---

## Notes

- **[P]** tasks = different files, no dependencies on incomplete tasks in the same batch.
- **[US1] / [US2] / [US3]** labels map tasks to their user story for traceability and independent shipping.
- Constitution II is load-bearing: write and verify tests **red** before implementation code lands for each user-story phase.
- Constitution IV is load-bearing: T038 + T039 (Phase 6) are the CI gate that prevents performance regression from silently shipping; don't defer them past the US3 release.
- Constitution III is load-bearing: the report section's omit-on-empty rule (T027) and the actionable-error message on bad `--sql-dialect` values (T018) are non-negotiable user-visible behavior.
- Avoid: bundling `extract_sql()` core work with embedded-SQL detection in a single PR (splits cleanly along the US1 vs US3 boundary); inlining `_render_sql_overview` into `generate()` inlining it (testability); any change to `graphify/cache.py` (constitution IV invariant — cache is already sufficient).
