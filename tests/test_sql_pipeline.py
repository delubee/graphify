from __future__ import annotations

import json
from pathlib import Path

from graphify.analyze import god_nodes, suggest_questions, surprising_connections
from graphify.build import build_from_json
from graphify.cluster import cluster, score_all
from graphify.detect import detect
from graphify.export import to_json
from graphify.extract import extract
from graphify.report import generate


SQL_FIXTURES = Path(__file__).parent / "fixtures" / "sql"


def test_sql_pipeline_end_to_end(tmp_path):
    detection = detect(SQL_FIXTURES)
    sql_files = [Path(path) for path in detection["files"]["sql"]]

    extraction = extract(sql_files, cache_root=tmp_path)
    graph = build_from_json(extraction)
    communities = cluster(graph)
    cohesion = score_all(graph, communities)
    labels = {cid: f"Community {cid}" for cid in communities}
    gods = god_nodes(graph)
    surprises = surprising_connections(graph, communities)
    questions = suggest_questions(graph, communities, labels)
    report = generate(
        graph,
        communities,
        cohesion,
        labels,
        gods,
        surprises,
        detection,
        {"input": 0, "output": 0},
        str(SQL_FIXTURES),
        suggested_questions=questions,
    )

    out = tmp_path / "graph.json"
    to_json(graph, communities, str(out))
    payload = json.loads(out.read_text(encoding="utf-8"))

    node_types = {node["type"] for node in payload["nodes"]}
    relations = {edge["relation"] for edge in payload["links"]}

    assert "sql" in detection["files"]
    assert {"sql_file", "statement", "table", "view", "cte"} <= node_types
    assert {"contains", "defines", "selects_from", "depends_on"} <= relations
    assert "SQL Overview" in report
    assert any("Which tables are written to by the most code paths?" in q["question"] for q in questions)


def test_incremental_cache_for_sql_files(tmp_path):
    detection = detect(SQL_FIXTURES)
    sql_files = [Path(path) for path in detection["files"]["sql"]]

    first = extract(sql_files, cache_root=tmp_path)
    second = extract(sql_files, cache_root=tmp_path)

    assert first["nodes"] == second["nodes"]
    assert first["edges"] == second["edges"]
