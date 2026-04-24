from __future__ import annotations

import ast
import re
from pathlib import Path

from sqlglot import parse_one

from . import statements
from .identifiers import _make_sql_id


_SQL_SHAPE = re.compile(r"^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|WITH)\b", re.IGNORECASE)


def _relative_path(path: Path, project_root: Path | None) -> str:
    if project_root is None:
        return str(path)
    try:
        return str(path.resolve().relative_to(project_root.resolve()))
    except ValueError:
        return str(path)


def _statement_node(statement_id: str, statement_type: str, sql_text: str, source_file: str, line_start: int, parse_status: str) -> dict:
    snippet = re.sub(r"\s+", " ", sql_text).strip()
    if len(snippet) > 300:
        snippet = snippet[:299] + "…"
    return {
        "id": statement_id,
        "type": "statement",
        "label": f"{statement_type} (L{line_start})",
        "statement_type": statement_type,
        "line_start": line_start,
        "line_end": line_start,
        "text_snippet": snippet,
        "parse_status": parse_status,
        "source_file": source_file,
        "source_location": f"L{line_start}",
        "file_type": "sql",
    }


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _function_node_id(path: Path, function_name: str, class_stack: list[str]) -> str:
    stem = path.stem
    if class_stack:
        class_id = _make_sql_id(stem, class_stack[-1])
        return _make_sql_id(class_id, function_name)
    return _make_sql_id(stem, function_name)


def detect_embedded(
    paths: list[Path],
    per_file_results: list[dict],
    *,
    project_root: Path | None = None,
    sql_dialect: str = "auto",
    sql_lineage: bool = False,
) -> dict:
    nodes: list[dict] = []
    edges: list[dict] = []
    seen_nodes: set[str] = set()
    seen_edges: set[tuple[str, str, str, str]] = set()
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
    read_dialect = None if sql_dialect == "auto" else sql_dialect

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

    for path, result in zip(paths, per_file_results):
        if path.suffix != ".py":
            continue
        source_file = _relative_path(path, project_root)
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        existing_ids = {node["id"] for node in result.get("nodes", [])}

        class Visitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.class_stack: list[str] = []
                self.function_stack: list[str] = []
                self.used_constants: set[int] = set()
                self.emitted: set[tuple[str, int]] = set()

            def _emit(self, sql_text: str, line_no: int, confidence: str) -> None:
                if not self.function_stack or not _SQL_SHAPE.match(sql_text):
                    return
                function_id = self.function_stack[-1]
                if function_id not in existing_ids:
                    return
                dedup_key = (function_id, line_no)
                if dedup_key in self.emitted:
                    return
                self.emitted.add(dedup_key)
                statement_id = _make_sql_id("stmt", source_file, "embedded", function_id, str(line_no))
                parse_status = "ok"
                error_message: str | None = None
                try:
                    expr = parse_one(sql_text, dialect=read_dialect, error_level="WARN")
                except Exception as exc:
                    expr = None
                    error_message = str(exc)
                stmt_type = statements.statement_type(expr, sql_text) if expr is not None else "UNKNOWN"
                if expr is None or stmt_type == "UNKNOWN":
                    parse_status = "failed"
                    confidence = "AMBIGUOUS"
                elif stmt_type in {"SELECT", "WITH"}:
                    tables = list(expr.find_all(statements.exp.Table))
                    if not tables or any(not getattr(table.this, "name", "") for table in tables):
                        parse_status = "failed"
                        confidence = "AMBIGUOUS"

                stmt_node = _statement_node(statement_id, stmt_type, sql_text, source_file, line_no, parse_status)
                if error_message:
                    stmt_node["error"] = error_message
                add_node(stmt_node)
                add_edge({
                    "source": function_id,
                    "target": statement_id,
                    "relation": "executes",
                    "confidence": confidence,
                    "source_file": source_file,
                    "source_location": f"L{line_no}",
                    "weight": 1.0,
                })
                if parse_status == "failed":
                    return
                handler = handler_map.get(stmt_type)
                if handler is None:
                    return
                stmt_nodes, stmt_edges = handler(
                    expr,
                    statement_id=statement_id,
                    file_id="",
                    default_schema="public",
                    source_file=source_file,
                    line_start=line_no,
                    object_level="column" if sql_lineage else "statement",
                    lineage=sql_lineage,
                )
                for node in stmt_nodes:
                    add_node(node)
                for edge in stmt_edges:
                    add_edge(edge)

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                self.class_stack.append(node.name)
                self.generic_visit(node)
                self.class_stack.pop()

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                self.function_stack.append(_function_node_id(path, node.name, self.class_stack))
                self.generic_visit(node)
                self.function_stack.pop()

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                self.function_stack.append(_function_node_id(path, node.name, self.class_stack))
                self.generic_visit(node)
                self.function_stack.pop()

            def visit_Call(self, node: ast.Call) -> None:
                call_name = _call_name(node.func)
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    sql_text = node.args[0].value
                    if call_name in {"execute", "executemany", "query", "raw", "text"}:
                        self.used_constants.add(id(node.args[0]))
                        self._emit(sql_text, node.lineno, "INFERRED")
                self.generic_visit(node)

            def visit_Constant(self, node: ast.Constant) -> None:
                if isinstance(node.value, str) and id(node) not in self.used_constants:
                    self._emit(node.value, node.lineno, "AMBIGUOUS")

        Visitor().visit(tree)

    return {"nodes": nodes, "edges": edges}
