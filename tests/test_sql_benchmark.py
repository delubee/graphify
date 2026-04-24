from __future__ import annotations

from graphify.benchmark import (
    measure_corpus_runtime,
    prepare_sql_benchmark_corpora,
    prepare_sql_corpus,
    run_sql_support_benchmarks,
)


def test_sql_benchmark_gate(tmp_path):
    no_sql = tmp_path / "bench-nosql"
    with_sql = tmp_path / "bench-withsql"
    prepare_sql_benchmark_corpora(no_sql, with_sql, code_file_count=320, sql_statements=10)

    baseline = measure_corpus_runtime(no_sql, repeats=2)
    with_sql_metrics = measure_corpus_runtime(with_sql, repeats=2)

    assert with_sql_metrics["wall_clock_s"] <= baseline["wall_clock_s"] * 1.15


def test_sql_benchmark_cases_exist(tmp_path):
    sql_root = tmp_path / "sql-corpus"
    prepare_sql_corpus(sql_root, file_count=10, total_statements=200)
    cases = run_sql_support_benchmarks(tmp_path / "cases")

    assert "sql_corpus" in cases
    assert "mixed_corpus_with_sql_added" in cases
    assert cases["sql_corpus"]["wall_clock_s"] >= 0
