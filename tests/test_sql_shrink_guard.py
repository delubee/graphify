from __future__ import annotations

import json
from pathlib import Path

from graphify.build import build_merge
from graphify.export import to_json
from graphify.detect import detect
from graphify.extract import extract


SQL_FIXTURES = Path(__file__).parent / "fixtures" / "sql"


def test_sql_failure_does_not_shrink_existing_graph(tmp_path, monkeypatch):
    detection = detect(SQL_FIXTURES)
    sql_files = [Path(path) for path in detection["files"]["sql"]]
    extraction = extract(sql_files, cache_root=tmp_path)

    graph_path = tmp_path / "graphify-out" / "graph.json"
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    graph = build_merge([extraction], graph_path)
    to_json(graph, {0: list(graph.nodes())}, str(graph_path))
    original = json.loads(graph_path.read_text(encoding="utf-8"))

    def _failed_extract(paths, cache_root=None):
        return {"nodes": [], "edges": [], "input_tokens": 0, "output_tokens": 0}

    monkeypatch.setattr("graphify.extract.extract", _failed_extract)

    merged = build_merge([_failed_extract(sql_files, cache_root=tmp_path)], graph_path)

    assert merged.number_of_nodes() >= len(original["nodes"])
