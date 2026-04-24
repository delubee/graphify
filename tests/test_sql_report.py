from __future__ import annotations

from pathlib import Path

from graphify.analyze import god_nodes, suggest_questions, surprising_connections
from graphify.build import build_from_json
from graphify.cluster import cluster, score_all
from graphify.detect import detect
from graphify.extract import extract
from graphify.report import generate


SQL_FIXTURES = Path(__file__).parent / "fixtures" / "sql"
def _make_report(root: Path, tmp_path: Path) -> tuple[str, list[dict]]:
    detection = detect(root)
    sql_files = [Path(path) for path in detection["files"].get("sql", [])]
    extraction = extract(sql_files, cache_root=tmp_path) if sql_files else {"nodes": [], "edges": [], "input_tokens": 0, "output_tokens": 0}
    graph = build_from_json(extraction)
    communities = cluster(graph) if graph.number_of_nodes() else {}
    cohesion = score_all(graph, communities) if communities else {}
    labels = {cid: f"Community {cid}" for cid in communities}
    gods = god_nodes(graph) if graph.number_of_nodes() else []
    surprises = surprising_connections(graph, communities) if graph.number_of_nodes() else []
    questions = suggest_questions(graph, communities, labels) if graph.number_of_nodes() else []
    report = generate(
        graph,
        communities,
        cohesion,
        labels,
        gods,
        surprises,
        detection,
        {"input": 0, "output": 0},
        str(root),
        suggested_questions=questions,
    )
    return report, questions


def test_report_includes_sql_overview_when_sql_present(tmp_path):
    report, questions = _make_report(SQL_FIXTURES, tmp_path)

    assert "## SQL Overview" in report
    assert "### Most-referenced tables" in report
    assert "`public.users`" in report
    assert "`public.orders`" in report
    assert "### Most-mutated tables" in report
    assert "### Views by dependency fan-in" in report
    assert "### SQL hotspots by file" in report
    assert sum(1 for q in questions if q.get("question") and "table" in q["question"].lower()) >= 2


def test_report_omits_sql_overview_without_sql(tmp_path):
    root = tmp_path / "nosql"
    root.mkdir()
    (root / "main.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    report, _ = _make_report(root, tmp_path)

    assert "## SQL Overview" not in report


def test_report_sql_rankings_are_stable(tmp_path):
    report, _ = _make_report(SQL_FIXTURES, tmp_path)

    users_pos = report.index("`public.users`")
    orders_pos = report.index("`public.orders`")
    audit_log_pos = report.index("`public.audit_log`")

    assert orders_pos < users_pos
    assert audit_log_pos > orders_pos
