from __future__ import annotations

from pathlib import Path

from graphify.analyze import god_nodes, surprising_connections, suggest_questions
from graphify.build import build_from_json
from graphify.cluster import cluster
from graphify.detect import detect
from graphify.extract import extract


SQL_FIXTURES = Path(__file__).parent / "fixtures" / "sql"


def test_sql_nodes_participate_in_analysis(tmp_path):
    detection = detect(SQL_FIXTURES)
    sql_files = [Path(path) for path in detection["files"]["sql"]]
    extraction = extract(sql_files, cache_root=tmp_path)
    graph = build_from_json(extraction)
    communities = cluster(graph)

    gods = god_nodes(graph)
    surprises = surprising_connections(graph, communities)
    questions = suggest_questions(graph, communities, {cid: f"Community {cid}" for cid in communities})

    assert any(node["label"] == "public.orders" for node in gods)
    assert isinstance(surprises, list)
    assert any("Which tables are written to by the most code paths?" == q.get("question") for q in questions)
