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


def test_embedded_sql_detects_js_ts_go_calls_even_with_sql_files_present(tmp_path):
    schema = tmp_path / "schema.sql"
    schema.write_text("CREATE TABLE users (id INT);", encoding="utf-8")

    js = tmp_path / "client.js"
    js.write_text(
        "function loadUsers(db) {\n"
        "  return db.query(\"SELECT name FROM users\");\n"
        "}\n",
        encoding="utf-8",
    )

    ts = tmp_path / "client.ts"
    ts.write_text(
        "export function loadOrders(db: any) {\n"
        "  return db.raw(`SELECT id FROM orders`)\n"
        "}\n",
        encoding="utf-8",
    )

    go = tmp_path / "main.go"
    go.write_text(
        "package main\n"
        "type DB interface{}\n"
        "func loadEmails(db DB) {\n"
        "    db.Query(\"SELECT email FROM users\")\n"
        "}\n",
        encoding="utf-8",
    )

    result = extract([schema, js, ts, go], sql_embedded=True)

    statements = _nodes_by_type(result, "statement")
    executes = _edges_by_relation(result, "executes")
    snippets = {node["text_snippet"] for node in statements}
    labels = {node["label"] for node in result["nodes"]}

    assert "loadUsers()" in labels
    assert "loadOrders()" in labels
    assert "loadEmails()" in labels
    assert any(snippet.startswith("SELECT name FROM users") for snippet in snippets)
    assert any(snippet.startswith("SELECT id FROM orders") for snippet in snippets)
    assert any(snippet.startswith("SELECT email FROM users") for snippet in snippets)
    assert len(executes) >= 3


def test_embedded_sql_heuristic_detection_works_for_js_and_go_string_literals(tmp_path):
    js = tmp_path / "heuristic.js"
    js.write_text(
        "function enqueueAudit() {\n"
        "  const sql = \"INSERT INTO audit_log(event) VALUES ('run')\";\n"
        "  return sql;\n"
        "}\n",
        encoding="utf-8",
    )

    go = tmp_path / "heuristic.go"
    go.write_text(
        "package main\n"
        "func cleanup() string {\n"
        "    sql := `DELETE FROM audit_log WHERE event = 'old'`\n"
        "    return sql\n"
        "}\n",
        encoding="utf-8",
    )

    result = extract([js, go], sql_embedded=True)

    statements = _nodes_by_type(result, "statement")
    executes = _edges_by_relation(result, "executes")

    assert any(node["text_snippet"].startswith("INSERT INTO audit_log") for node in statements)
    assert any(node["text_snippet"].startswith("DELETE FROM audit_log") for node in statements)
    assert any(edge["confidence"] == "AMBIGUOUS" for edge in executes)
