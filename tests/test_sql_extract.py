from __future__ import annotations

from pathlib import Path

import pytest

from graphify.sql import extract_sql


SQL_FIXTURES = Path(__file__).parent / "fixtures" / "sql"


def _nodes_by_type(result: dict, node_type: str) -> list[dict]:
    return [node for node in result["nodes"] if node["type"] == node_type]


def _edges_by_relation(result: dict, relation: str) -> list[dict]:
    return [edge for edge in result["edges"] if edge["relation"] == relation]


def test_extract_sql_create_table_and_columns():
    result = extract_sql(SQL_FIXTURES / "schema.sql", object_level="column", project_root=SQL_FIXTURES.parent)

    sql_files = _nodes_by_type(result, "sql_file")
    tables = _nodes_by_type(result, "table")
    columns = _nodes_by_type(result, "column")
    references = _edges_by_relation(result, "references")

    assert len(sql_files) == 1
    assert sql_files[0]["parse_status"] == "ok"
    assert {table["qualified_name"] for table in tables} >= {"public.users", "public.orders"}
    assert any(column["qualified_name"] == "public.users.email" for column in columns)
    assert any(edge["confidence"] == "EXTRACTED" for edge in references)


def test_extract_sql_view_and_cte_dependencies():
    views = extract_sql(SQL_FIXTURES / "views.sql", project_root=SQL_FIXTURES.parent)
    queries = extract_sql(SQL_FIXTURES / "queries.sql", project_root=SQL_FIXTURES.parent)

    view_nodes = _nodes_by_type(views, "view")
    materialized = _nodes_by_type(views, "materialized_view")
    ctes = _nodes_by_type(queries, "cte")
    depends_on = _edges_by_relation(views, "depends_on")
    joins = _edges_by_relation(queries, "joins")

    assert any(node["qualified_name"] == "public.active_users" for node in view_nodes)
    assert any(node["qualified_name"] == "public.daily_order_totals" for node in materialized)
    assert any(node["cte_name"] == "recent_orders" for node in ctes)
    assert len(depends_on) >= 3
    assert any(edge["relation"] == "joins" for edge in joins)


def test_extract_sql_partial_failure_uses_fallback():
    result = extract_sql(SQL_FIXTURES / "malformed.sql", project_root=SQL_FIXTURES.parent)

    sql_file = _nodes_by_type(result, "sql_file")[0]
    tables = _nodes_by_type(result, "table")

    assert sql_file["parse_status"] in {"partial", "failed"}
    assert {table["qualified_name"] for table in tables} >= {"public.good_one", "public.also_good"}
    assert result["errors"]


def test_extract_sql_default_schema_resolution():
    result = extract_sql(SQL_FIXTURES / "multi_schema.sql", project_root=SQL_FIXTURES.parent)

    sql_file = _nodes_by_type(result, "sql_file")[0]
    selects = _edges_by_relation(result, "selects_from")
    tables = {node["qualified_name"] for node in _nodes_by_type(result, "table")}

    assert sql_file["default_schema"] == "analytics"
    assert "analytics.events" in tables
    assert any(edge["confidence"] == "INFERRED" for edge in selects)


def test_extract_sql_object_level_file_only():
    result = extract_sql(SQL_FIXTURES / "schema.sql", object_level="file", project_root=SQL_FIXTURES.parent)

    assert [node["type"] for node in result["nodes"]] == ["sql_file"]
    assert result["edges"] == []


def test_extract_sql_invalid_dialect_raises():
    with pytest.raises(ValueError, match="invalid --sql-dialect value 'bogus'"):
        extract_sql(SQL_FIXTURES / "schema.sql", dialect="bogus")


def test_extract_sql_id_stability():
    first = extract_sql(SQL_FIXTURES / "queries.sql", object_level="column", project_root=SQL_FIXTURES.parent)
    second = extract_sql(SQL_FIXTURES / "queries.sql", object_level="column", project_root=SQL_FIXTURES.parent)

    assert first["nodes"] == second["nodes"]
    assert first["edges"] == second["edges"]


def test_extract_sql_handles_giant_fixture(giant_sql: Path):
    result = extract_sql(giant_sql, object_level="statement", project_root=giant_sql.parent)

    sql_file = _nodes_by_type(result, "sql_file")[0]
    statements = _nodes_by_type(result, "statement")

    assert sql_file["statement_count"] >= 1000
    assert len(statements) >= 1000
