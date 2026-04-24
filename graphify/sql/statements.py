from __future__ import annotations

from typing import Any

from sqlglot import exp

from .identifiers import _make_sql_id, normalize_identifier, qualify, qualify_column


def _line_location(line_start: int) -> str:
    return f"L{line_start}"


def _identifier_name(identifier: Any) -> str:
    if identifier is None:
        return ""
    quoted = getattr(identifier, "quoted", False)
    name = getattr(identifier, "name", None)
    if name is None:
        name = str(identifier)
    return normalize_identifier(name, quoted=quoted)


def _table_parts(table_expr: exp.Table, default_schema: str) -> tuple[str, str]:
    schema_expr = table_expr.args.get("db")
    schema_name = _identifier_name(schema_expr.this if hasattr(schema_expr, "this") else schema_expr) if schema_expr else default_schema
    object_name = _identifier_name(table_expr.this)
    return schema_name or default_schema, object_name


def table_node(table_expr: exp.Table, *, default_schema: str, source_file: str, source_location: str, node_type: str = "table") -> dict:
    schema_name, object_name = _table_parts(table_expr, default_schema)
    qualified_name = qualify(schema_name, object_name)
    return {
        "id": _make_sql_id(node_type, schema_name, object_name),
        "type": node_type,
        "label": qualified_name,
        "schema_name": schema_name,
        "object_name": object_name,
        "qualified_name": qualified_name,
        "source_file": source_file,
        "source_location": source_location,
        "file_type": "sql",
    }


def column_node(
    *,
    schema_name: str,
    object_name: str,
    column_name: str,
    parent_table_id: str,
    source_file: str,
    source_location: str,
    declared_type: str | None = None,
) -> dict:
    qualified_name = qualify_column(schema_name, object_name, column_name)
    return {
        "id": _make_sql_id("col", schema_name, object_name, column_name),
        "type": "column",
        "label": qualified_name,
        "parent_table_id": parent_table_id,
        "schema_name": schema_name,
        "object_name": object_name,
        "column_name": column_name,
        "qualified_name": qualified_name,
        "declared_type": declared_type,
        "source_file": source_file,
        "source_location": source_location,
        "file_type": "sql",
    }


def relation_edge(
    source: str,
    target: str,
    relation: str,
    *,
    source_file: str,
    source_location: str,
    confidence: str,
) -> dict:
    return {
        "source": source,
        "target": target,
        "relation": relation,
        "confidence": confidence,
        "source_file": source_file,
        "source_location": source_location,
        "weight": 1.0,
    }


def statement_type(expr: exp.Expression, statement_text: str) -> str:
    if isinstance(expr, exp.Create):
        if any(prop.__class__.__name__ == "MaterializedProperty" for prop in (expr.args.get("properties") or exp.Properties()).expressions):
            return "CREATE_MATERIALIZED_VIEW"
        kind = str(expr.args.get("kind", "")).upper()
        if kind == "TABLE":
            return "CREATE_TABLE"
        if kind == "VIEW":
            return "CREATE_VIEW"
    if isinstance(expr, exp.Alter):
        return "ALTER_TABLE"
    if isinstance(expr, exp.Select):
        return "WITH" if expr.args.get("with") else "SELECT"
    if isinstance(expr, exp.Insert):
        return "INSERT"
    if isinstance(expr, exp.Update):
        return "UPDATE"
    if isinstance(expr, exp.Delete):
        return "DELETE"
    text = statement_text.strip().upper()
    if text.startswith("SET "):
        return "UNKNOWN"
    return "UNKNOWN"


def handle_create_table(
    expr: exp.Create,
    *,
    statement_id: str,
    file_id: str,
    default_schema: str,
    source_file: str,
    line_start: int,
    object_level: str,
) -> tuple[list[dict], list[dict]]:
    source_location = _line_location(line_start)
    table = table_node(expr.this.this if isinstance(expr.this, exp.Schema) else expr.this, default_schema=default_schema, source_file=source_file, source_location=source_location)
    table["defining_file"] = source_file
    nodes = [table]
    edges = [
        relation_edge(file_id, table["id"], "defines", source_file=source_file, source_location=source_location, confidence="EXTRACTED"),
    ]

    schema_expr = expr.this if isinstance(expr.this, exp.Schema) else None
    if not schema_expr:
        return nodes, edges

    for column_def in schema_expr.expressions:
        if not isinstance(column_def, exp.ColumnDef):
            continue
        column_name = _identifier_name(column_def.this)
        declared_type = column_def.args.get("kind")
        declared_type_str = declared_type.sql() if declared_type is not None else None
        if object_level == "column":
            column = column_node(
                schema_name=table["schema_name"],
                object_name=table["object_name"],
                column_name=column_name,
                parent_table_id=table["id"],
                source_file=source_file,
                source_location=source_location,
                declared_type=declared_type_str,
            )
            nodes.append(column)
            edges.append(relation_edge(table["id"], column["id"], "has_column", source_file=source_file, source_location=source_location, confidence="EXTRACTED"))
        for constraint in column_def.args.get("constraints") or []:
            kind = constraint.args.get("kind")
            if isinstance(kind, exp.Reference):
                ref_schema = kind.this
                ref_table = ref_schema.this if isinstance(ref_schema, exp.Schema) else ref_schema
                ref_node = table_node(ref_table, default_schema=default_schema, source_file=source_file, source_location=source_location)
                nodes.append(ref_node)
                edges.append(relation_edge(table["id"], ref_node["id"], "references", source_file=source_file, source_location=source_location, confidence="EXTRACTED"))
    return nodes, edges


def _view_node_type(expr: exp.Create) -> str:
    if any(prop.__class__.__name__ == "MaterializedProperty" for prop in (expr.args.get("properties") or exp.Properties()).expressions):
        return "materialized_view"
    return "view"


def _select_table_nodes(
    select_expr: exp.Expression,
    *,
    statement_id: str,
    default_schema: str,
    source_file: str,
    source_location: str,
    include_columns: bool,
) -> tuple[list[dict], list[dict]]:
    nodes: list[dict] = []
    edges: list[dict] = []
    cte_names = {cte.alias_or_name for cte in select_expr.find_all(exp.CTE)}
    cte_ids: dict[str, str] = {}
    joined_tables = set()
    for join in select_expr.find_all(exp.Join):
        for table_expr in join.find_all(exp.Table):
            joined_tables.add(table_expr.sql())

    for cte in select_expr.find_all(exp.CTE):
        cte_name = normalize_identifier(cte.alias_or_name)
        cte_id = _make_sql_id("cte", source_file, statement_id, cte_name)
        nodes.append({
            "id": cte_id,
            "type": "cte",
            "label": f"WITH {cte_name} ({source_location})",
            "cte_name": cte_name,
            "enclosing_statement_id": statement_id,
            "source_file": source_file,
            "source_location": source_location,
            "file_type": "sql",
        })
        cte_ids[cte_name] = cte_id
        edges.append(relation_edge(statement_id, cte_id, "uses_cte", source_file=source_file, source_location=source_location, confidence="EXTRACTED"))

    for table_expr in select_expr.find_all(exp.Table):
        table_name = normalize_identifier(table_expr.this.name if hasattr(table_expr.this, "name") else str(table_expr.this))
        if table_name in cte_names:
            if table_expr.sql() in joined_tables:
                edges.append(relation_edge(statement_id, cte_ids[table_name], "joins", source_file=source_file, source_location=source_location, confidence="EXTRACTED"))
            continue
        table = table_node(table_expr, default_schema=default_schema, source_file=source_file, source_location=source_location)
        nodes.append(table)
        relation = "joins" if table_expr.sql() in joined_tables else "selects_from"
        confidence = "EXTRACTED" if table_expr.args.get("db") else "INFERRED"
        edges.append(relation_edge(statement_id, table["id"], relation, source_file=source_file, source_location=source_location, confidence=confidence))

    return nodes, edges


def handle_create_view(
    expr: exp.Create,
    *,
    statement_id: str,
    file_id: str,
    default_schema: str,
    source_file: str,
    line_start: int,
    object_level: str,
) -> tuple[list[dict], list[dict]]:
    source_location = _line_location(line_start)
    view_type = _view_node_type(expr)
    view = table_node(expr.this, default_schema=default_schema, source_file=source_file, source_location=source_location, node_type=view_type)
    view["defining_file"] = source_file
    nodes = [view]
    edges = [relation_edge(file_id, view["id"], "defines", source_file=source_file, source_location=source_location, confidence="EXTRACTED")]
    if expr.expression is not None:
        dep_nodes, dep_edges = _select_table_nodes(
            expr.expression,
            statement_id=statement_id,
            default_schema=default_schema,
            source_file=source_file,
            source_location=source_location,
            include_columns=object_level == "column",
        )
        nodes.extend(dep_nodes)
        for edge in dep_edges:
            if edge["relation"] in {"selects_from", "joins"}:
                edges.append(relation_edge(view["id"], edge["target"], "depends_on", source_file=source_file, source_location=source_location, confidence=edge["confidence"]))
    return nodes, edges


def handle_create_materialized_view(
    expr: exp.Create,
    *,
    statement_id: str,
    file_id: str,
    default_schema: str,
    source_file: str,
    line_start: int,
    object_level: str,
) -> tuple[list[dict], list[dict]]:
    return handle_create_view(
        expr,
        statement_id=statement_id,
        file_id=file_id,
        default_schema=default_schema,
        source_file=source_file,
        line_start=line_start,
        object_level=object_level,
    )


def handle_alter_table(
    expr: exp.Alter,
    *,
    statement_id: str,
    file_id: str | None = None,
    default_schema: str,
    source_file: str,
    line_start: int,
    object_level: str,
) -> tuple[list[dict], list[dict]]:
    table_expr = expr.this
    source_location = _line_location(line_start)
    if not isinstance(table_expr, exp.Table):
        return [], []
    table = table_node(table_expr, default_schema=default_schema, source_file=source_file, source_location=source_location)
    return [table], [relation_edge(statement_id, table["id"], "updates", source_file=source_file, source_location=source_location, confidence="EXTRACTED")]


def handle_select(
    expr: exp.Select,
    *,
    statement_id: str,
    file_id: str | None = None,
    default_schema: str,
    source_file: str,
    line_start: int,
    object_level: str,
) -> tuple[list[dict], list[dict]]:
    return _select_table_nodes(
        expr,
        statement_id=statement_id,
        default_schema=default_schema,
        source_file=source_file,
        source_location=_line_location(line_start),
        include_columns=object_level == "column",
    )


def handle_with(
    expr: exp.Select,
    *,
    statement_id: str,
    file_id: str | None = None,
    default_schema: str,
    source_file: str,
    line_start: int,
    object_level: str,
) -> tuple[list[dict], list[dict]]:
    return handle_select(
        expr,
        statement_id=statement_id,
        default_schema=default_schema,
        source_file=source_file,
        line_start=line_start,
        object_level=object_level,
    )


def handle_insert(
    expr: exp.Insert,
    *,
    statement_id: str,
    file_id: str | None = None,
    default_schema: str,
    source_file: str,
    line_start: int,
    object_level: str,
) -> tuple[list[dict], list[dict]]:
    source_location = _line_location(line_start)
    target = expr.this.this if isinstance(expr.this, exp.Schema) else expr.this
    if not isinstance(target, exp.Table):
        return [], []
    table = table_node(target, default_schema=default_schema, source_file=source_file, source_location=source_location)
    return [table], [relation_edge(statement_id, table["id"], "inserts_into", source_file=source_file, source_location=source_location, confidence="INFERRED" if not target.args.get("db") else "EXTRACTED")]


def handle_update(
    expr: exp.Update,
    *,
    statement_id: str,
    file_id: str | None = None,
    default_schema: str,
    source_file: str,
    line_start: int,
    object_level: str,
) -> tuple[list[dict], list[dict]]:
    source_location = _line_location(line_start)
    table_expr = expr.this
    if not isinstance(table_expr, exp.Table):
        return [], []
    table = table_node(table_expr, default_schema=default_schema, source_file=source_file, source_location=source_location)
    return [table], [relation_edge(statement_id, table["id"], "updates", source_file=source_file, source_location=source_location, confidence="INFERRED" if not table_expr.args.get("db") else "EXTRACTED")]


def handle_delete(
    expr: exp.Delete,
    *,
    statement_id: str,
    file_id: str | None = None,
    default_schema: str,
    source_file: str,
    line_start: int,
    object_level: str,
) -> tuple[list[dict], list[dict]]:
    source_location = _line_location(line_start)
    table_expr = expr.this
    if isinstance(table_expr, exp.From):
        table_expr = table_expr.this
    if not isinstance(table_expr, exp.Table):
        return [], []
    table = table_node(table_expr, default_schema=default_schema, source_file=source_file, source_location=source_location)
    return [table], [relation_edge(statement_id, table["id"], "deletes_from", source_file=source_file, source_location=source_location, confidence="INFERRED" if not table_expr.args.get("db") else "EXTRACTED")]
