# Feature Specification: Powerful SQL Native Support

**Feature Branch**: `001-sql-native-support`
**Created**: 2026-04-24
**Status**: Draft
**Input**: User description: "为仓库 delubee/graphify 设计一个『功能强大的 SQL 原生支持』功能规格 — promote `.sql` from an almost-unsupported file type to a first-class knowledge source across graphify's detect, extract, analyze, report, and query flow. Covers detection, structured extraction (tables/views/columns/CTEs/statements), relationship modeling (selects_from, joins, inserts_into, updates, deletes_from, defines, depends_on, has_column, uses_cte, derives_from), SQL-specific analysis and report insights, graceful degradation on parse failure, and a phased roadmap that reserves room for embedded-SQL detection and column-level lineage as later enhancements."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Scan a SQL-Heavy Repository and See Real Structure (Priority: P1) 🎯 MVP

A developer runs `graphify .` on a repository that contains database migrations, schema files,
and canned queries under paths like `db/migrations/*.sql`, `schema/*.sql`, `queries/*.sql`.
Today, graphify effectively skips those files or treats them as opaque documents. With this
feature, graphify detects `.sql` as a first-class code input, parses it structurally, and
produces a knowledge graph that tells the user *what tables and views exist, which queries
read them, and which queries mutate them*.

**Why this priority**: This is the MVP. Without first-class `.sql` detection and structural
extraction, none of the downstream value (insights, reports, embedded-SQL linking) is
possible. A repo with 200 migration files and 0 SQL nodes in the graph is a credibility gap.

**Independent Test**: Point graphify at a fixture repo containing `schema.sql`, `views.sql`,
`queries.sql`, and `migrations/*.sql`. Verify that `graph.json` contains SQL file nodes,
statement nodes, and entity nodes (tables, views, columns, CTEs) with the correct
relationships connecting them.

**Acceptance Scenarios**:

1. **Given** a repo containing `schema.sql` with `CREATE TABLE users (id INT, email TEXT)`,
   **When** the user runs `graphify .`,
   **Then** `graph.json` contains a `sql_file` node for `schema.sql`, a `statement` node for
   the `CREATE TABLE`, a `table` node `users`, and `column` nodes `id` and `email`, with
   `defines` and `has_column` edges wired between them.
2. **Given** a repo containing `queries.sql` with a `SELECT ... FROM users JOIN orders`
   statement, **When** graphify extracts, **Then** the corresponding `statement` node has
   `selects_from` edges to `users` and `orders` and a `joins` edge to `orders`.
3. **Given** a repo containing `views.sql` with `CREATE VIEW active_users AS SELECT ...
   FROM users`, **When** graphify extracts, **Then** a `view` node `active_users` exists
   with a `depends_on` edge to `users`.
4. **Given** a repo containing a multi-statement SQL file with 20 statements, **When**
   graphify extracts, **Then** all 20 statements appear as distinct `statement` nodes,
   each linked to the parent `sql_file` node via `contains`.
5. **Given** a SQL file where one statement fails to parse (malformed / unsupported
   dialect construct), **When** graphify extracts, **Then** the `sql_file` node still
   exists, parseable statements are still captured, and the failed statement is recorded
   with an error marker — the file is not dropped in its entirety.
6. **Given** the user adds `migrations/` to `.graphifyignore`, **When** graphify runs,
   **Then** no `.sql` files under `migrations/` appear in the graph.
7. **Given** the user modifies a `.sql` file after an initial run, **When** `graphify watch`
   is running or `graphify update .` is invoked, **Then** the changed file is re-parsed and
   the graph is updated to reflect added/removed/renamed entities.

---

### User Story 2 - SQL-Specific Insights in the Audit Report (Priority: P2)

After the graph is built, a developer opens `graphify-out/GRAPH_REPORT.md` and can see
SQL-specific insights at a glance: the most-referenced tables, the most-mutated tables,
views with the highest dependency fan-in, and SQL hotspots across files. The report also
proposes SQL-oriented "Suggested Questions" the user can ask an assistant against the
graph.

**Why this priority**: Structural nodes in `graph.json` are necessary but not sufficient.
Users who open GRAPH_REPORT.md expect the same quality of insight graphify already
provides for Python / TS / Go. Without this, SQL support feels half-done.

**Independent Test**: Against the fixture repo from US1, verify that `GRAPH_REPORT.md`
contains a "SQL Overview" section with populated rankings for most-referenced tables,
most-mutated tables, and views ordered by dependency fan-in.

**Acceptance Scenarios**:

1. **Given** a graph that contains SQL nodes and at least 5 tables with varying reference
   counts, **When** the report is generated, **Then** `GRAPH_REPORT.md` includes a "SQL
   Overview" section listing the top tables by `selects_from` inbound count.
2. **Given** a graph where certain tables have many `inserts_into` / `updates` /
   `deletes_from` edges, **When** the report is generated, **Then** the report highlights
   "most-mutated tables" separately from "most-referenced tables".
3. **Given** views with varying `depends_on` fan-in, **When** the report is generated,
   **Then** the report ranks views by dependency fan-in.
4. **Given** a graph with SQL nodes, **When** the report is generated, **Then** the
   "Suggested Questions" block includes at least 3 SQL-oriented questions (e.g.,
   "Which tables are written to by the most code paths?", "Which views fan out to the
   largest number of base tables?", "Are there tables defined in schema but never
   referenced?").
5. **Given** a graph with zero SQL nodes, **When** the report is generated, **Then** the
   SQL Overview section is omitted (not left as a stub).

---

### User Story 3 - Embedded SQL and Column-Level Lineage (Priority: P3)

A developer running graphify on a Python / TypeScript repo where code issues SQL via
string literals, ORM calls, or query builders gets links between the *code function that
runs the SQL* and the *tables/columns it touches*. As an optional enhancement, column-level
lineage (`derives_from`) is populated for supported SELECT patterns so a user can ask
"which columns feed the `monthly_revenue` view?" and get a concrete answer.

**Why this priority**: High value but architecturally more expensive. The MVP (US1) and
report integration (US2) must land first to validate the node/edge model. P3 extends the
model rather than redefining it, which is why it is last.

**Independent Test**: Against a fixture repo containing a Python module that executes a
SQL string literal `SELECT id FROM users WHERE email = ?`, verify that the Python
function node has a relationship (`executes` or similar) to the corresponding SQL
statement node, and that `users` appears as `selects_from` downstream.

**Acceptance Scenarios**:

1. **Given** a Python function with a top-level `cursor.execute("SELECT ... FROM users")`,
   **When** graphify extracts with `--sql-embedded` enabled, **Then** the function node
   is linked to a synthesized `statement` node, which in turn `selects_from` the `users`
   table node (if the `users` node exists from any other source).
2. **Given** a SQL file with a SELECT that projects `a.id, b.name` from a join,
   **When** graphify extracts with `--sql-lineage` enabled, **Then** the resulting view
   or output columns carry `derives_from` edges back to `a.id` and `b.name`.
3. **Given** embedded SQL that cannot be parsed (dynamic string building), **When**
   graphify extracts, **Then** the code function is still captured, a best-effort
   structured record is attached (with an AMBIGUOUS provenance marker), and the file is
   not dropped.

---

### Edge Cases

- **Unqualified table references**: A query like `SELECT * FROM orders` in a file that
  never declares a schema. The system MUST resolve to a default namespace (configurable,
  defaulting to the first schema declared in the file, or `public` if none), and MUST
  mark the resolution as `INFERRED` so users can audit guesses.
- **Dialect-specific syntax**: A PostgreSQL-only construct (e.g., `CREATE EXTENSION`,
  `ON CONFLICT`) in a file parsed as generic SQL. The statement MUST still be captured
  with best-effort structure; unrecognized clauses produce `AMBIGUOUS` markers rather
  than dropping the statement.
- **Very large SQL files**: A single `.sql` file with 10,000+ statements (e.g., a seed
  dump). Extraction MUST not hold the entire parsed AST in memory at once, and MUST
  respect the SHA256 cache so unchanged files are not re-parsed.
- **Duplicate table names across schemas**: `sales.users` and `analytics.users` are
  distinct entities. Node IDs MUST be stable across runs and MUST NOT collide.
- **Files that are not SQL despite the `.sql` extension**: Binary files, empty files,
  files that contain only comments. These MUST produce at most a `sql_file` node with
  appropriate metadata and MUST NOT raise.
- **Case sensitivity**: Identifiers `Users` and `users` — resolution MUST follow a stable
  rule (lowercase by default, matching ANSI SQL conventions), and the chosen rule MUST
  be documented.
- **Chained CTEs**: A `WITH a AS (...), b AS (SELECT FROM a) SELECT ...`. Both CTE nodes
  MUST exist with correct `depends_on` and `uses_cte` edges.
- **Generated / templated SQL**: Files produced by a template engine (e.g., `{{ table }}`
  placeholders). The file MUST be treated as unparseable but preserved as a `sql_file`
  node with an error marker.

## Requirements *(mandatory)*

### Functional Requirements

**File Detection**

- **FR-001**: The system MUST recognize `.sql` as a first-class source extension in the
  file detection stage, on equal footing with `.py`, `.ts`, `.go`, etc.
- **FR-002**: File-watch mode MUST monitor `.sql` file changes and trigger incremental
  re-extraction of only the changed files.
- **FR-003**: The incremental file collection path MUST include `.sql` files in its
  enumeration, honoring the existing SHA256 cache.
- **FR-004**: `.graphifyignore` rules MUST apply to `.sql` files using the same glob /
  gitignore-style syntax the project already uses for other file types.

**Structured Extraction**

- **FR-005**: The system MUST expose a dedicated SQL extractor (conceptually
  `extract_sql(path) -> dict`) rather than retrofitting the generic OOP-language
  extractor, because SQL's structure is table/query-oriented, not class-oriented.
- **FR-006**: The extractor MUST handle multi-statement SQL files, producing one
  `statement` node per top-level statement.
- **FR-007**: For each `.sql` file, the extractor MUST produce a `sql_file` node with
  `path`, `sha256`, and `statement_count` metadata.
- **FR-008**: For each significant statement (CREATE TABLE, CREATE VIEW, CREATE
  MATERIALIZED VIEW, ALTER TABLE, SELECT, INSERT, UPDATE, DELETE, WITH/CTE top-level),
  the extractor MUST produce a `statement` node with `statement_type`, `line_start`,
  `line_end`, and a normalized text snippet.
- **FR-009**: For each defined table / view / materialized view / column / CTE, the
  extractor MUST produce a corresponding entity node.
- **FR-010**: The extractor MUST emit the following edges when supported by the statement
  structure: `contains` (file→statement), `defines` (file→table/view), `selects_from`
  (statement→table/view), `joins` (statement→table/view), `inserts_into` (statement→
  table), `updates` (statement→table), `deletes_from` (statement→table), `has_column`
  (table→column), `depends_on` (view→table/view), `uses_cte` (statement→cte).
- **FR-011**: Column-level lineage (`derives_from` edges) MUST be implementable as an
  additive enhancement (see Phased Plan — Phase 3) without requiring changes to
  Phase 1/2 node shapes.
- **FR-012**: When the primary SQL parser fails on a file, the extractor MUST still emit
  a `sql_file` node with an error marker and SHOULD attempt a weak/regex-based fallback
  to recover obvious object definitions. The file MUST NOT be silently dropped.
- **FR-013**: When the primary SQL parser fails on a *single statement* within an
  otherwise-parseable file, the extractor MUST still emit `statement` nodes for the
  parseable statements and mark the failing statement with an error marker.
- **FR-014**: Parse failures MUST be logged with file path, statement index (if
  available), and parser error message, and MUST NOT raise an exception that terminates
  the extraction run.

**Embedded SQL (Phase 3 scope — hooks present from Phase 1)**

- **FR-015**: The node/edge model MUST reserve capacity for an `executes` / equivalent
  edge from code-function nodes to `statement` nodes, so a Phase 3 implementation does
  not require migrating Phase 1 graphs.
- **FR-016**: A CLI flag `--sql-embedded` MUST exist and MUST default to `off` in
  Phase 1 and Phase 2. When enabled in Phase 3, it activates embedded-SQL detection
  from code literals.

**Node and Edge Identity**

- **FR-017**: Node IDs for `table`, `view`, `materialized_view`, and `column` MUST be
  derived from a qualified name including schema (falling back to a default namespace
  when unqualified) so the same entity referenced from multiple files collapses to a
  single node.
- **FR-018**: Node IDs for `statement` MUST be derived from file path + statement index
  (or a content hash) so the same statement re-appears with a stable ID across runs.
- **FR-019**: Node IDs for `cte` MUST be scoped to their enclosing statement (CTEs are
  not globally addressable).
- **FR-020**: All SQL nodes MUST carry an `extraction_provenance` attribute of
  `EXTRACTED`, `INFERRED`, or `AMBIGUOUS`, matching graphify's existing convention.
- **FR-021**: Node attributes MUST include `schema_name`, `object_name`, and
  `statement_type` where applicable, to support downstream filtering and reporting.

**Analysis and Reporting**

- **FR-022**: The analysis stage MUST include SQL entities in hotspot / god-node
  computations on the same footing as code entities.
- **FR-023**: `GRAPH_REPORT.md` MUST include a "SQL Overview" section (when the graph
  contains any SQL nodes) with at minimum: most-referenced tables (by `selects_from`
  fan-in), most-mutated tables (by `inserts_into` + `updates` + `deletes_from` fan-in),
  views ranked by `depends_on` fan-in, and SQL hotspot files (by statement count or
  entity reference count).
- **FR-024**: The "Suggested Questions" block MUST include at least 3 SQL-oriented
  prompts when SQL nodes are present.
- **FR-025**: When the graph contains zero SQL nodes, the SQL Overview section MUST be
  omitted (no empty stubs).

**CLI / Configuration**

- **FR-026**: A `--sql-dialect` flag MUST exist. Default: dialect-agnostic / ANSI-first
  parse. Accepted values include at minimum: `postgres`, `mysql`, `sqlite`, `tsql`,
  `oracle`, `ansi`. Invalid values MUST produce a clear error.
- **FR-027**: A `--sql-lineage` flag MUST exist. Default: `off`. When enabled,
  `derives_from` edges are populated (Phase 3).
- **FR-028**: A `--sql-embedded` flag MUST exist (see FR-016).
- **FR-029**: A `--sql-object-level` flag MUST exist. Default: `statement`. Accepted
  values: `file` (aggregate all SQL into file-level nodes only), `statement` (default,
  statement-level nodes), `column` (include column nodes). This controls graph
  verbosity for very large SQL corpora.

**Degradation and Safety**

- **FR-030**: No SQL-related failure MUST ever corrupt the existing non-SQL portion of
  the graph. SQL extraction runs in an isolated try/except boundary.
- **FR-031**: The `graphify-out/` directory MUST remain excluded from source scanning
  (this is already an invariant; SQL support MUST NOT break it even if a previous run
  wrote `.sql` files into `graphify-out/`).
- **FR-032**: The shrink-guard on `to_json()` MUST continue to protect against SQL
  extraction regressions that would produce a smaller graph than a prior run.

### Key Entities

- **SQL File (`sql_file`)**: Represents a single `.sql` file on disk. Attributes:
  `path`, `sha256`, `statement_count`, `parse_status` (`ok` / `partial` / `failed`).
- **Statement (`statement`)**: Represents one top-level SQL statement. Attributes:
  `statement_type` (CREATE_TABLE, SELECT, INSERT, ...), `line_start`, `line_end`,
  `text_snippet` (normalized), `parse_status`.
- **Table (`table`)**: A named base table. Attributes: `schema_name`, `object_name`,
  `qualified_name`, `defining_file` (optional — the file that declared it, if found).
- **View (`view`)**: A named view. Same shape as `table` plus `is_materialized` flag.
  (`materialized_view` is reported as a distinct `node_type`.)
- **Column (`column`)**: A named column on a table or view. Attributes: `parent_table`,
  `column_name`, `declared_type` (best-effort), `qualified_name`.
- **CTE (`cte`)**: A Common Table Expression. Attributes: `cte_name`,
  `enclosing_statement_id`.
- **Function / Procedure (`sql_function`, `sql_procedure`)**: Reserved node types for
  Phase 3. Present in the type inventory from Phase 1 but not populated until later.
- **Edges** (recap): `contains`, `defines`, `selects_from`, `joins`, `inserts_into`,
  `updates`, `deletes_from`, `has_column`, `depends_on`, `uses_cte`, `derives_from`
  (Phase 3), `executes` (Phase 3).

## Phased Plan

### Phase 1 — Detection and Structural Extraction (MVP, ships US1)

- Add `.sql` to the recognized source extension list.
- Implement the dedicated SQL extractor.
- Emit `sql_file`, `statement`, `table`, `view`, `materialized_view`, `column`, `cte`
  nodes and the core edges (all edges in FR-010).
- Stable node IDs per FR-017 through FR-019.
- Graceful degradation: per-file and per-statement fallback per FR-012 / FR-013.
- `.graphifyignore`, watch, cache, and shrink-guard integration.
- Fixtures: `schema.sql`, `views.sql`, `queries.sql`, `migrations/*.sql`, at least one
  intentionally malformed file to exercise fallback.

### Phase 2 — Analysis and Reporting (ships US2)

- Analysis stage consumes SQL nodes for hotspot and god-node computation.
- `GRAPH_REPORT.md` gains the "SQL Overview" section (FR-023).
- "Suggested Questions" gains SQL-oriented prompts (FR-024).
- CLI: `--sql-dialect`, `--sql-object-level` surfaced.
- No new node types; purely additive at the report / analysis layer.

### Phase 3 — Embedded SQL and Column-Level Lineage (ships US3)

- Activate `--sql-embedded` to extract SQL from Python / JS / Go string literals, ORM
  / query builder call patterns (best effort; marked `INFERRED`).
- Populate `executes` edges from code-function nodes to `statement` nodes.
- Activate `--sql-lineage` to populate `derives_from` edges for SELECT projection paths.
- Populate `sql_function` / `sql_procedure` nodes for CREATE FUNCTION / CREATE
  PROCEDURE statements.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a repository containing 100+ `.sql` files totaling 10,000+ SQL
  statements, graphify completes a full extraction without any file being silently
  dropped, and produces at least one node per file in `graph.json`.
- **SC-002**: On a curated fixture covering CREATE TABLE, ALTER TABLE, CREATE VIEW,
  CREATE MATERIALIZED VIEW, SELECT, INSERT, UPDATE, DELETE, and WITH/CTE, graphify
  correctly emits the expected node and edge counts for each statement type with at
  least 95% precision, measured against a hand-authored golden graph.
- **SC-003**: `graph.json` generated from a SQL-bearing repository contains at minimum
  the node types: `sql_file`, `statement`, `table`, `view`, `column`, `cte` (others as
  the repo demands).
- **SC-004**: `GRAPH_REPORT.md` generated from the same repository contains a "SQL
  Overview" section with populated rankings for most-referenced tables, most-mutated
  tables, and views by dependency fan-in.
- **SC-005**: When a user modifies one `.sql` file, `graphify update .` or
  `graphify watch` re-processes only that file (cache-hit on the rest) and the graph
  reflects the change within one incremental cycle.
- **SC-006**: When a SQL file is malformed, the file still appears in the graph as a
  `sql_file` node with `parse_status = failed` or `partial`, and extraction of other
  files in the same run is unaffected.
- **SC-007**: Default-invocation cost: on the benchmark fixture, adding SQL support
  increases total extraction wall-clock time by no more than 15% vs the pre-feature
  baseline on the same (non-SQL) corpus — i.e., SQL support MUST NOT slow down users
  who have no `.sql` files.
- **SC-008**: Graph size sanity: on a repository with N SQL statements, the resulting
  SQL-related node count is bounded by roughly `O(N + tables + columns)`; the extractor
  does not produce node-per-token explosion.
- **SC-009**: On repositories with zero `.sql` files, behavior is identical to the
  pre-feature baseline — no empty SQL sections in the report, no extra nodes, no
  performance impact beyond the detection fast-path.
- **SC-010**: Users can ask an assistant SQL-oriented questions ("Which tables are
  most written to?") against the graph and receive grounded answers backed by the
  SQL nodes, without the assistant having to re-read raw `.sql` files.

## Assumptions

- **Primary parser**: A mature, actively-maintained, Python-native, multi-dialect SQL
  parser will be used as the primary parsing engine. `sqlglot` is the recommended
  choice because it covers the five major dialects required (Postgres, MySQL, SQLite,
  T-SQL, Oracle) from a single Python dependency, is actively maintained, and exposes
  a statement-level iteration API suited to graphify's streaming needs.
  `tree-sitter-sql` is noted as a future alternative but is **not** the primary path
  in this spec.
- **Dialect default**: When no `--sql-dialect` is specified, the parser is invoked in
  its most permissive / dialect-agnostic mode. Per-file dialect hints (e.g., a comment
  or directory convention) are **out of scope** for Phase 1.
- **Identifier casing**: Unquoted identifiers are normalized to lowercase for ID
  derivation, matching ANSI SQL expectations. Quoted identifiers preserve case.
- **Default schema**: Unqualified table / view references resolve to `public` unless
  the file declares a schema (e.g., `SET search_path = ...` or `CREATE SCHEMA ...`
  earlier in the file), in which case the declared schema is used. Ambiguous
  resolutions are marked `INFERRED`.
- **Embedded SQL scope (Phase 3)**: Initial embedded-SQL detection targets string
  literals passed to well-known execute / query call patterns (e.g., DB-API cursor
  execute, SQLAlchemy `text(...)`, common query-builder entry points). ORM model
  introspection is out of scope for the initial Phase 3 cut.
- **No live database access**: Extraction is 100% static. graphify MUST NOT connect to
  any database server for metadata; all structure is derived from the files.
- **Python baseline**: Graphify's existing Python 3.10+ baseline applies. Any new
  parser dependency MUST support Python 3.10+.
- **Determinism**: SQL structural extraction is deterministic given the same file
  contents. No LLM is involved in SQL structural extraction — the LLM layer remains
  reserved for the existing concept/relationship inference pass that runs over docs
  and transcripts.

## Testing Expectations

- **Detection tests**: assert `.sql` files are enumerated, watched, and subject to
  `.graphifyignore`.
- **Extractor unit tests**: per-statement-type tests covering CREATE TABLE, ALTER
  TABLE, CREATE VIEW, CREATE MATERIALIZED VIEW, SELECT, INSERT, UPDATE, DELETE,
  WITH/CTE, and multi-statement files.
- **Fixtures**: `tests/fixtures/sql/schema.sql`, `views.sql`, `queries.sql`,
  `migrations/001_init.sql`, `malformed.sql`, `empty.sql`, `giant.sql` (≥1000
  statements), `multi_schema.sql`.
- **Graph assertions**: given a fixture repo, assert the presence and connectivity of
  key nodes (e.g., `table:public.users`, `view:public.active_users`, the edges
  `active_users -[depends_on]-> users`), and the absence of accidental duplicates.
- **Fallback tests**: assert that a malformed file still produces a `sql_file` node
  with `parse_status` set appropriately, and that other files in the same run are
  unaffected.
- **Cache / watch / incremental tests**: modify one `.sql` file, re-run, assert only
  that file is re-parsed.
- **Performance regression test**: assert SC-007 (≤15% overhead on a non-SQL corpus)
  as a CI gate.

## Risks & Open Questions

- **Dialect ambiguity**: Truly dialect-specific syntax (e.g., PG `RETURNING`, T-SQL
  `OUTPUT`, MySQL `INSERT ... ON DUPLICATE KEY UPDATE`) may yield weak or
  `AMBIGUOUS`-marked structure in dialect-agnostic mode. Users with dialect-heavy
  corpora SHOULD set `--sql-dialect`.
- **Dynamic SQL**: String-concatenated or templated SQL cannot be extracted
  structurally. Phase 3 embedded-SQL detection will intentionally mark these as
  `AMBIGUOUS` rather than attempting to over-promise.
- **Column lineage fidelity**: `derives_from` (Phase 3) is acknowledged to be
  *best-effort*, not *provably complete*, especially across subqueries and set
  operations. This is an explicit non-goal; users MUST see the `INFERRED` /
  `AMBIGUOUS` provenance markers to know what's trustworthy.
- **Very-large-file memory**: 10k+-statement SQL dumps require streaming extraction.
  The implementation plan MUST verify the primary parser supports statement-by-
  statement iteration without materializing the whole AST.
- **ORM coverage (Phase 3)**: ORM / query-builder surface area is enormous.
  Which ORMs / query builders are in Phase 3 initial scope is a question to resolve
  at `/speckit.plan` time, not a spec-level decision.
- **Qualified-name canonicalization**: When a project mixes `public.users`,
  `"public"."users"`, and unqualified `users`, the canonicalization rule (Assumption
  above) must be exercised against real-world examples before GA to confirm no
  collisions or unintended merges occur.
