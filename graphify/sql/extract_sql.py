from __future__ import annotations

import hashlib
import re
from pathlib import Path

from sqlglot import exp, parse_one

from .fallback import scan_sql_fallback
from .identifiers import _make_sql_id, resolve_default_schema
from .model import SqlError, SqlExtractionResult
from . import statements

VALID_DIALECTS = ("auto", "postgres", "mysql", "sqlite", "tsql", "oracle", "ansi")
VALID_OBJECT_LEVELS = ("file", "statement", "column")


def _relative_path(path: Path, project_root: Path | None) -> str:
    if project_root is None:
        return str(path)
    try:
        return str(path.resolve().relative_to(project_root.resolve()))
    except ValueError:
        return str(path)


def _statement_segments(text: str) -> list[tuple[str, int, int, int]]:
    segments: list[tuple[str, int, int, int]] = []
    start = 0
    line_start = 1
    index = 0
    for part in text.split(";"):
        segment = part.strip()
        line_count = part.count("\n")
        if segment:
            lines = part.splitlines() or [part]
            start_offset = 0
            for line in lines:
                if line.strip():
                    break
                start_offset += 1
            end_offset = 0
            for line in reversed(lines):
                if line.strip():
                    break
                end_offset += 1
            seg_line_start = line_start + start_offset
            seg_line_end = line_start + max(len(lines) - end_offset - 1, 0)
            segments.append((segment, seg_line_start, seg_line_end, index))
            index += 1
        line_start += line_count + 1
        start += len(part) + 1
    return segments


def _statement_node(
    *,
    source_file: str,
    statement_index: int,
    statement_type: str,
    statement_text: str,
    line_start: int,
    line_end: int,
    parse_status: str,
) -> dict:
    snippet = re.sub(r"\s+", " ", statement_text).strip()
    if len(snippet) > 300:
        snippet = snippet[:299] + "…"
    return {
        "id": _make_sql_id("stmt", source_file, str(statement_index)),
        "type": "statement",
        "label": f"{statement_type} ({'L' + str(line_start)})",
        "statement_type": statement_type,
        "line_start": line_start,
        "line_end": line_end,
        "text_snippet": snippet,
        "parse_status": parse_status,
        "source_file": source_file,
        "source_location": f"L{line_start}",
        "file_type": "sql",
    }


def extract_sql(
    path: Path,
    *,
    dialect: str = "auto",
    object_level: str = "statement",
    project_root: Path | None = None,
    lineage: bool = False,
) -> SqlExtractionResult:
    if dialect not in VALID_DIALECTS:
        valid = ", ".join(VALID_DIALECTS)
        raise ValueError(f"invalid --sql-dialect value '{dialect}'. valid: {valid}")
    if object_level not in VALID_OBJECT_LEVELS:
        raise ValueError(f"invalid sql object level '{object_level}'")

    if not Path(path).exists():
        raise FileNotFoundError(path)

    raw = Path(path).read_bytes()
    text = raw.decode("utf-8", errors="replace")
    sha256 = hashlib.sha256(raw).hexdigest()
    source_file = _relative_path(Path(path), project_root)
    default_schema = resolve_default_schema(text)

    file_id = _make_sql_id("file", source_file)
    file_node = {
        "id": file_id,
        "type": "sql_file",
        "label": source_file,
        "path": source_file,
        "sha256": sha256,
        "statement_count": 0,
        "parse_status": "ok",
        "default_schema": default_schema,
        "source_file": source_file,
        "source_location": "L1",
        "file_type": "sql",
    }
    if object_level == "file":
        return {"nodes": [file_node], "edges": [], "errors": []}

    nodes: list[dict] = [file_node]
    edges: list[dict] = []
    errors: list[SqlError] = []
    seen_nodes = {file_id}
    seen_edges: set[tuple[str, str, str, str]] = set()
    success_count = 0
    failed_count = 0

    def add_node(node: dict) -> None:
        if node["id"] in seen_nodes:
            return
        seen_nodes.add(node["id"])
        nodes.append(node)

    def add_edge(edge: dict) -> None:
        key = (edge["source"], edge["target"], edge["relation"], edge["source_location"])
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append(edge)

    segments = _statement_segments(text)
    if not segments:
        fallback_nodes, _ = scan_sql_fallback(text, default_schema=default_schema, source_file=source_file, source_location="L1")
        for node in fallback_nodes:
            add_node(node)
        file_node["parse_status"] = "failed"
        file_node["statement_count"] = 0
        file_node["parser_error"] = "No SQL statements found"
        errors.append({"path": source_file, "line": None, "message": "No SQL statements found"})
        return {"nodes": nodes, "edges": edges, "errors": errors}

    handler_map = {
        "CREATE_TABLE": statements.handle_create_table,
        "CREATE_VIEW": statements.handle_create_view,
        "CREATE_MATERIALIZED_VIEW": statements.handle_create_materialized_view,
        "CREATE_FUNCTION": statements.handle_create_function,
        "CREATE_PROCEDURE": statements.handle_create_procedure,
        "ALTER_TABLE": statements.handle_alter_table,
        "SELECT": statements.handle_select,
        "WITH": statements.handle_with,
        "INSERT": statements.handle_insert,
        "UPDATE": statements.handle_update,
        "DELETE": statements.handle_delete,
    }

    read_dialect = None if dialect == "auto" else dialect

    for statement_text, line_start, line_end, index in segments:
        parse_status = "ok"
        error_message: str | None = None
        try:
            expr = parse_one(statement_text, dialect=read_dialect, error_level="WARN")
        except Exception as exc:
            expr = None
            error_message = str(exc)

        stmt_type = statements.statement_type(expr, statement_text) if expr is not None else "UNKNOWN"
        if expr is None or (stmt_type == "UNKNOWN" and not statement_text.strip().upper().startswith("SET ")):
            parse_status = "failed"
            failed_count += 1
            error_message = error_message or "Unsupported SQL statement"
        else:
            success_count += 1

        stmt_node = _statement_node(
            source_file=source_file,
            statement_index=index,
            statement_type=stmt_type,
            statement_text=statement_text,
            line_start=line_start,
            line_end=line_end,
            parse_status=parse_status,
        )
        if error_message:
            stmt_node["error"] = error_message
        add_node(stmt_node)
        add_edge(statements.relation_edge(file_id, stmt_node["id"], "contains", source_file=source_file, source_location=f"L{line_start}", confidence="EXTRACTED"))

        if parse_status == "failed":
            errors.append({"path": source_file, "line": line_start, "message": error_message or "Unsupported SQL statement"})
            fallback_nodes, fallback_edges = scan_sql_fallback(
                statement_text,
                default_schema=default_schema,
                source_file=source_file,
                source_location=f"L{line_start}",
            )
            for node in fallback_nodes:
                add_node(node)
            for edge in fallback_edges:
                add_edge(edge)
            continue

        handler = handler_map.get(stmt_type)
        if handler is None:
            continue
        stmt_nodes, stmt_edges = handler(
            expr,
            statement_id=stmt_node["id"],
            file_id=file_id,
            default_schema=default_schema,
            source_file=source_file,
            line_start=line_start,
            object_level=object_level,
            lineage=lineage,
        )
        for node in stmt_nodes:
            add_node(node)
        for edge in stmt_edges:
            add_edge(edge)

    file_node["statement_count"] = len(segments)
    if failed_count and success_count:
        file_node["parse_status"] = "partial"
    elif failed_count and not success_count:
        file_node["parse_status"] = "failed"
    else:
        file_node["parse_status"] = "ok"
    if errors:
        file_node["parser_error"] = "; ".join(err["message"] for err in errors[:3])

    return {"nodes": nodes, "edges": edges, "errors": errors}
