from __future__ import annotations

import re

from .identifiers import _make_sql_id, normalize_identifier, qualify


_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("table", re.compile(r"CREATE\s+TABLE\s+([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)", re.IGNORECASE)),
    ("view", re.compile(r"CREATE\s+VIEW\s+([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)", re.IGNORECASE)),
    (
        "materialized_view",
        re.compile(r"CREATE\s+MATERIALIZED\s+VIEW\s+([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)", re.IGNORECASE),
    ),
    ("insert", re.compile(r"INSERT\s+INTO\s+([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)", re.IGNORECASE)),
    ("update", re.compile(r"UPDATE\s+([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)", re.IGNORECASE)),
    ("delete", re.compile(r"DELETE\s+FROM\s+([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)", re.IGNORECASE)),
    ("from", re.compile(r"FROM\s+([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)", re.IGNORECASE)),
)


def _split_name(raw: str, default_schema: str) -> tuple[str, str]:
    parts = raw.split(".", 1)
    if len(parts) == 2:
        schema_name, object_name = parts
    else:
        schema_name, object_name = default_schema, parts[0]
    return normalize_identifier(schema_name), normalize_identifier(object_name)


def scan_sql_fallback(
    text: str,
    *,
    default_schema: str,
    source_file: str,
    source_location: str,
) -> tuple[list[dict], list[dict]]:
    nodes: list[dict] = []
    edges: list[dict] = []
    seen_nodes: set[str] = set()
    seen_edges: set[tuple[str, str, str, str]] = set()

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

    for kind, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            schema_name, object_name = _split_name(match.group(1), default_schema)
            qualified_name = qualify(schema_name, object_name)
            node_type = kind if kind in {"table", "view", "materialized_view"} else "table"
            node_id = _make_sql_id(node_type, schema_name, object_name)
            add_node({
                "id": node_id,
                "type": node_type,
                "label": qualified_name,
                "schema_name": schema_name,
                "object_name": object_name,
                "qualified_name": qualified_name,
                "defining_file": source_file if node_type in {"table", "view", "materialized_view"} else None,
                "source_file": source_file,
                "source_location": source_location,
                "file_type": "sql",
            })
    return nodes, edges
