from __future__ import annotations

from pathlib import Path

from graphify.extract import extract


def _nodes_by_type(result: dict, node_type: str) -> list[dict]:
    return [node for node in result["nodes"] if node.get("type") == node_type]


def _edges_by_relation(result: dict, relation: str) -> list[dict]:
    return [edge for edge in result["edges"] if edge["relation"] == relation]


def test_embedded_sql_detects_execute_and_text_calls(tmp_path):
    app = tmp_path / "app.py"
    app.write_text(
        "from sqlalchemy import text\n"
        "def recent_emails(conn):\n"
        "    return conn.execute(\"SELECT email FROM users WHERE created_at > '2026-01-01'\").fetchall()\n"
        "def totals(conn):\n"
        "    stmt = text(\"SELECT total_cents FROM orders\")\n"
        "    return conn.execute(stmt).fetchall()\n",
        encoding="utf-8",
    )

    result = extract([app], sql_embedded=True)

    statements = _nodes_by_type(result, "statement")
    executes = _edges_by_relation(result, "executes")
    selects = _edges_by_relation(result, "selects_from")

    assert any(node["text_snippet"].startswith("SELECT email FROM users") for node in statements)
    assert any(node["text_snippet"].startswith("SELECT total_cents FROM orders") for node in statements)
    assert len(executes) >= 2
    assert any(edge["target"].endswith("users") for edge in selects)
    assert any(edge["target"].endswith("orders") for edge in selects)


def test_embedded_sql_ignores_orm_model_strings(tmp_path):
    app = tmp_path / "models.py"
    app.write_text(
        "class User:\n"
        "    __tablename__ = 'users'\n"
        "    __table_args__ = {'schema': 'public'}\n",
        encoding="utf-8",
    )

    result = extract([app], sql_embedded=True)

    assert _nodes_by_type(result, "statement") == []
    assert _edges_by_relation(result, "executes") == []


def test_embedded_sql_parse_failure_is_ambiguous_and_keeps_function(tmp_path):
    app = tmp_path / "broken.py"
    app.write_text(
        "def broken(conn):\n"
        "    return conn.execute(\"SELECT FROM\").fetchall()\n",
        encoding="utf-8",
    )

    result = extract([app], sql_embedded=True)

    function_labels = {node["label"] for node in result["nodes"]}
    executes = _edges_by_relation(result, "executes")

    assert "broken()" in function_labels
    assert any(edge["confidence"] == "AMBIGUOUS" for edge in executes)


def test_embedded_sql_disabled_by_default(tmp_path):
    app = tmp_path / "app.py"
    app.write_text(
        "def recent_emails(conn):\n"
        "    return conn.execute(\"SELECT email FROM users\").fetchall()\n",
        encoding="utf-8",
    )

    result = extract([app])

    assert _nodes_by_type(result, "statement") == []
    assert _edges_by_relation(result, "executes") == []
