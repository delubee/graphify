from __future__ import annotations

import ast
import importlib
import re
from dataclasses import dataclass
from pathlib import Path

from sqlglot import parse_one

from graphify.extract import _make_id

from . import statements
from .identifiers import _make_sql_id


_SQL_SHAPE = re.compile(r"^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|WITH)\b", re.IGNORECASE)
_KNOWN_SQL_CALLS = {
    "exec",
    "execcontext",
    "execute",
    "executemany",
    "query",
    "queryrow",
    "raw",
    "text",
}


@dataclass(frozen=True)
class _TreeSitterSpec:
    ts_module: str
    ts_language_fn: str
    class_types: frozenset[str]
    function_types: frozenset[str]
    string_types: frozenset[str]
    arrow_lexical_declarations: bool = False
    go_package_scope: bool = False


_SPECS: dict[str, _TreeSitterSpec] = {
    ".py": _TreeSitterSpec(
        ts_module="tree_sitter_python",
        ts_language_fn="language",
        class_types=frozenset({"class_definition"}),
        function_types=frozenset({"function_definition"}),
        string_types=frozenset({"string", "concatenated_string"}),
    ),
    ".js": _TreeSitterSpec(
        ts_module="tree_sitter_javascript",
        ts_language_fn="language",
        class_types=frozenset({"class_declaration"}),
        function_types=frozenset({"function_declaration", "method_definition"}),
        string_types=frozenset({"string", "template_string"}),
        arrow_lexical_declarations=True,
    ),
    ".ts": _TreeSitterSpec(
        ts_module="tree_sitter_typescript",
        ts_language_fn="language_typescript",
        class_types=frozenset({"class_declaration", "interface_declaration"}),
        function_types=frozenset({"function_declaration", "method_definition"}),
        string_types=frozenset({"string", "template_string"}),
        arrow_lexical_declarations=True,
    ),
    ".tsx": _TreeSitterSpec(
        ts_module="tree_sitter_typescript",
        ts_language_fn="language_typescript",
        class_types=frozenset({"class_declaration", "interface_declaration"}),
        function_types=frozenset({"function_declaration", "method_definition"}),
        string_types=frozenset({"string", "template_string"}),
        arrow_lexical_declarations=True,
    ),
    ".go": _TreeSitterSpec(
        ts_module="tree_sitter_go",
        ts_language_fn="language",
        class_types=frozenset(),
        function_types=frozenset({"function_declaration", "method_declaration"}),
        string_types=frozenset({"interpreted_string_literal", "raw_string_literal"}),
        go_package_scope=True,
    ),
}


def _relative_path(path: Path, project_root: Path | None) -> str:
    if project_root is None:
        return str(path)
    try:
        return str(path.resolve().relative_to(project_root.resolve()))
    except ValueError:
        return str(path)


def _read_text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


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


def _load_parser(spec: _TreeSitterSpec):
    mod = importlib.import_module(spec.ts_module)
    from tree_sitter import Language, Parser

    lang_fn = getattr(mod, spec.ts_language_fn)
    language = Language(lang_fn())
    return Parser(language)


def _strip_quotes(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'", "`"}:
        return raw[1:-1]
    return raw


def _string_value(node, source: bytes, suffix: str) -> str:
    raw = _read_text(node, source)
    if suffix == ".py":
        try:
            value = ast.literal_eval(raw)
        except Exception:
            value = _strip_quotes(raw)
        return value if isinstance(value, str) else raw
    if node.type == "template_string":
        return _strip_quotes(raw)
    if node.type in {"interpreted_string_literal", "raw_string_literal", "string"}:
        return _strip_quotes(raw)
    return raw


def _call_name(node, source: bytes):
    function_node = node.child_by_field_name("function")
    if function_node is None:
        return None
    raw = _read_text(function_node, source).strip()
    if not raw:
        return None
    return raw.split(".")[-1].lower()


def _first_argument_strings(node, spec: _TreeSitterSpec):
    arguments = node.child_by_field_name("arguments")
    if arguments is None:
        return []
    return [child for child in arguments.named_children[:1] if child.type in spec.string_types]


def _python_docstring_node(node) -> bool:
    if node.type not in {"string", "concatenated_string"}:
        return False
    parent = node.parent
    grandparent = parent.parent if parent else None
    if parent is None or grandparent is None:
        return False
    if parent.type != "expression_statement" or grandparent.type not in {"module", "block"}:
        return False
    named_children = list(grandparent.named_children)
    return bool(named_children and named_children[0] == parent)


def _python_class_id(node, stem: str, source: bytes) -> str | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    return _make_id(stem, _read_text(name_node, source))


def _python_function_id(node, stem: str, source: bytes, class_id: str | None) -> str | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    func_name = _read_text(name_node, source)
    return _make_id(class_id, func_name) if class_id else _make_id(stem, func_name)


def _js_class_id(node, stem: str, source: bytes) -> str | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    return _make_id(stem, _read_text(name_node, source))


def _js_function_id(node, stem: str, source: bytes, class_id: str | None) -> str | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    func_name = _read_text(name_node, source)
    return _make_id(class_id, func_name) if class_id else _make_id(stem, func_name)


def _go_function_id(node, path: Path, source: bytes) -> str | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    func_name = _read_text(name_node, source)
    if node.type == "method_declaration":
        receiver = node.child_by_field_name("receiver")
        receiver_type: str | None = None
        if receiver is not None:
            for child in receiver.named_children:
                type_node = child.child_by_field_name("type")
                if type_node is not None:
                    receiver_type = _read_text(type_node, source).lstrip("*").strip()
                    break
        if receiver_type:
            pkg_scope = path.parent.name or path.stem
            parent_id = _make_id(pkg_scope, receiver_type)
            return _make_id(parent_id, func_name)
    return _make_id(path.stem, func_name)


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
        spec = _SPECS.get(path.suffix)
        if spec is None:
            continue
        try:
            parser = _load_parser(spec)
            source = path.read_bytes()
            tree = parser.parse(source)
            root = tree.root_node
        except Exception:
            continue

        source_file = _relative_path(path, project_root)
        existing_ids = {node["id"] for node in result.get("nodes", [])}
        used_string_ranges: set[tuple[int, int]] = set()
        emitted: set[tuple[str, int, int]] = set()

        def emit_sql(sql_text: str, line_no: int, start_byte: int, function_id: str | None, confidence: str) -> None:
            if function_id is None or function_id not in existing_ids or not _SQL_SHAPE.match(sql_text):
                return
            dedup_key = (function_id, line_no, start_byte)
            if dedup_key in emitted:
                return
            emitted.add(dedup_key)

            statement_id = _make_sql_id("stmt", source_file, "embedded", function_id, str(line_no), str(start_byte))
            parse_status = "ok"
            error_message: str | None = None
            try:
                expr = parse_one(sql_text, dialect=read_dialect, error_level="IGNORE")
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

        def walk(node, current_class_id: str | None = None, current_function_id: str | None = None) -> None:
            node_type = node.type

            if spec.ts_module == "tree_sitter_python" and node_type in spec.class_types:
                class_id = _python_class_id(node, path.stem, source)
                body = node.child_by_field_name("body")
                if body is not None:
                    for child in body.children:
                        walk(child, class_id, None)
                return

            if spec.ts_module in {"tree_sitter_javascript", "tree_sitter_typescript"} and node_type in spec.class_types:
                class_id = _js_class_id(node, path.stem, source)
                body = node.child_by_field_name("body")
                if body is not None:
                    for child in body.children:
                        walk(child, class_id, None)
                return

            if node_type in spec.function_types:
                if spec.go_package_scope:
                    function_id = _go_function_id(node, path, source)
                elif spec.ts_module == "tree_sitter_python":
                    function_id = _python_function_id(node, path.stem, source, current_class_id)
                else:
                    function_id = _js_function_id(node, path.stem, source, current_class_id)
                body = node.child_by_field_name("body")
                if body is not None:
                    walk(body, current_class_id, function_id)
                return

            if spec.arrow_lexical_declarations and node_type == "lexical_declaration":
                handled_arrow = False
                for child in node.named_children:
                    if child.type != "variable_declarator":
                        continue
                    value = child.child_by_field_name("value")
                    name_node = child.child_by_field_name("name")
                    if value is None or value.type != "arrow_function" or name_node is None:
                        continue
                    handled_arrow = True
                    function_id = _make_id(path.stem, _read_text(name_node, source))
                    body = value.child_by_field_name("body")
                    if body is not None:
                        walk(body, current_class_id, function_id)
                if handled_arrow:
                    return

            if current_function_id is not None and node_type in {"call", "call_expression"}:
                call_name = _call_name(node, source)
                if call_name in _KNOWN_SQL_CALLS:
                    for arg in _first_argument_strings(node, spec):
                        sql_text = _string_value(arg, source, path.suffix)
                        used_string_ranges.add((arg.start_byte, arg.end_byte))
                        emit_sql(sql_text, arg.start_point[0] + 1, arg.start_byte, current_function_id, "INFERRED")

            if current_function_id is not None and node_type in spec.string_types:
                string_range = (node.start_byte, node.end_byte)
                if string_range not in used_string_ranges:
                    if not (spec.ts_module == "tree_sitter_python" and _python_docstring_node(node)):
                        sql_text = _string_value(node, source, path.suffix)
                        emit_sql(sql_text, node.start_point[0] + 1, node.start_byte, current_function_id, "AMBIGUOUS")

            for child in node.children:
                walk(child, current_class_id, current_function_id)

        walk(root)

    return {"nodes": nodes, "edges": edges}
