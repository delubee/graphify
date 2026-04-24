from __future__ import annotations

from pathlib import Path

from graphify.sql import extract_sql


def _edges_by_relation(result: dict, relation: str) -> list[dict]:
    return [edge for edge in result["edges"] if edge["relation"] == relation]


def _nodes_by_type(result: dict, node_type: str) -> list[dict]:
    return [node for node in result["nodes"] if node["type"] == node_type]


def test_lineage_simple_projection(tmp_path):
    path = tmp_path / "simple.sql"
    path.write_text("CREATE VIEW picked_ids AS SELECT a.id FROM a;", encoding="utf-8")

    result = extract_sql(path, object_level="column", project_root=tmp_path, lineage=True)

    columns = {node["qualified_name"] for node in _nodes_by_type(result, "column")}
    derives = _edges_by_relation(result, "derives_from")

    assert "public.picked_ids.id" in columns
    assert any(edge["source"].endswith("picked_ids_id") and edge["target"].endswith("a_id") for edge in derives)


def test_lineage_join_projection(tmp_path):
    path = tmp_path / "join.sql"
    path.write_text(
        "CREATE VIEW joined_view AS "
        "SELECT a.id, b.name FROM a JOIN b ON b.a_id = a.id;",
        encoding="utf-8",
    )

    result = extract_sql(path, object_level="column", project_root=tmp_path, lineage=True)
    derives = _edges_by_relation(result, "derives_from")

    assert any(edge["source"].endswith("joined_view_id") and edge["target"].endswith("a_id") for edge in derives)
    assert any(edge["source"].endswith("joined_view_name") and edge["target"].endswith("b_name") for edge in derives)


def test_lineage_cte_projection(tmp_path):
    path = tmp_path / "cte.sql"
    path.write_text(
        "CREATE VIEW cte_view AS "
        "WITH c AS (SELECT a.id FROM a) "
        "SELECT c.id FROM c;",
        encoding="utf-8",
    )

    result = extract_sql(path, object_level="column", project_root=tmp_path, lineage=True)
    derives = _edges_by_relation(result, "derives_from")

    assert any(edge["source"].endswith("cte_view_id") and edge["target"].endswith("a_id") for edge in derives)


def test_lineage_union_marks_ambiguous(tmp_path):
    path = tmp_path / "union.sql"
    path.write_text(
        "CREATE VIEW union_view AS "
        "SELECT a.id AS id FROM a UNION SELECT b.id AS id FROM b;",
        encoding="utf-8",
    )

    result = extract_sql(path, object_level="column", project_root=tmp_path, lineage=True)
    derives = _edges_by_relation(result, "derives_from")

    assert derives
    assert all(edge["confidence"] == "AMBIGUOUS" for edge in derives)
