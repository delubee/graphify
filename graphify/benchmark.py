"""Token-reduction benchmark - measures how much context graphify saves vs naive full-corpus approach."""
from __future__ import annotations
import json
import shutil
import time
from pathlib import Path
import networkx as nx
from networkx.readwrite import json_graph


_CHARS_PER_TOKEN = 4  # standard approximation


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _query_subgraph_tokens(G: nx.Graph, question: str, depth: int = 3) -> int:
    """Run BFS from best-matching nodes and return estimated tokens in the subgraph context."""
    terms = [t.lower() for t in question.split() if len(t) > 2]
    scored = []
    for nid, data in G.nodes(data=True):
        label = data.get("label", "").lower()
        score = sum(1 for t in terms if t in label)
        if score > 0:
            scored.append((score, nid))
    scored.sort(reverse=True)
    start_nodes = [nid for _, nid in scored[:3]]
    if not start_nodes:
        return 0

    visited: set[str] = set(start_nodes)
    frontier = set(start_nodes)
    edges_seen: list[tuple] = []
    for _ in range(depth):
        next_frontier: set[str] = set()
        for n in frontier:
            for neighbor in G.neighbors(n):
                if neighbor not in visited:
                    next_frontier.add(neighbor)
                    edges_seen.append((n, neighbor))
        visited.update(next_frontier)
        frontier = next_frontier

    lines = []
    for nid in visited:
        d = G.nodes[nid]
        lines.append(f"NODE {d.get('label', nid)} src={d.get('source_file', '')} loc={d.get('source_location', '')}")
    for u, v in edges_seen:
        if u in visited and v in visited:
            d = G.edges[u, v]
            lines.append(f"EDGE {G.nodes[u].get('label', u)} --{d.get('relation', '')}--> {G.nodes[v].get('label', v)}")

    return _estimate_tokens("\n".join(lines))


_SAMPLE_QUESTIONS = [
    "how does authentication work",
    "what is the main entry point",
    "how are errors handled",
    "what connects the data layer to the api",
    "what are the core abstractions",
]


def prepare_sql_benchmark_corpora(
    no_sql_root: str | Path,
    with_sql_root: str | Path,
    *,
    code_file_count: int = 240,
    sql_statements: int = 40,
) -> None:
    """Create synthetic corpora for SQL performance comparisons.

    `no_sql_root` contains only Python files.
    `with_sql_root` contains the same Python files plus one `.sql` file.
    """
    no_sql_root = Path(no_sql_root)
    with_sql_root = Path(with_sql_root)
    for root in (no_sql_root, with_sql_root):
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)

    for idx in range(code_file_count):
        rel = Path("pkg") / f"mod_{idx}.py"
        body = (
            f"def func_{idx}(value: int) -> int:\n"
            f"    total = value + {idx}\n"
            f"    for step in range(3):\n"
            f"        total += step\n"
            f"    return total\n"
        )
        for root in (no_sql_root, with_sql_root):
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")

    sql_lines = []
    for idx in range(sql_statements):
        sql_lines.append(f"CREATE TABLE bench_{idx} (id INTEGER PRIMARY KEY, value TEXT);")
        sql_lines.append(f"INSERT INTO bench_{idx} (id, value) VALUES ({idx}, 'value {idx}');")
    sql_path = with_sql_root / "db" / "benchmark.sql"
    sql_path.parent.mkdir(parents=True, exist_ok=True)
    sql_path.write_text("\n".join(sql_lines) + "\n", encoding="utf-8")


def prepare_sql_corpus(root: str | Path, *, file_count: int = 500, total_statements: int = 50_000) -> None:
    """Create a large SQL-only corpus for stress benchmarks."""
    root = Path(root)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    per_file = max(1, total_statements // file_count)
    stmt_idx = 0
    for file_idx in range(file_count):
        path = root / "sql" / f"batch_{file_idx:03d}.sql"
        path.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        for _ in range(per_file):
            lines.append(f"CREATE TABLE bench_{stmt_idx} (id INTEGER PRIMARY KEY, value TEXT);")
            stmt_idx += 1
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def measure_corpus_runtime(root: str | Path, *, repeats: int = 2) -> dict:
    """Measure detect+extract wall clock and peak RSS for a local corpus."""
    from graphify.detect import detect
    from graphify.extract import extract

    root = Path(root)
    wall_clock_samples: list[float] = []
    peak_rss_samples: list[int] = []

    for idx in range(repeats):
        start = time.perf_counter()
        detection = detect(root)
        files = [Path(path) for bucket in detection["files"].values() for path in bucket if path.endswith((".py", ".sql"))]
        cache_root = root / f".bench-cache-{idx}"
        extract(files, cache_root=cache_root)
        wall_clock_samples.append(time.perf_counter() - start)
        try:
            import resource

            peak_rss_samples.append(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        except Exception:
            pass
        shutil.rmtree(cache_root, ignore_errors=True)

    return {
        "wall_clock_s": min(wall_clock_samples) if wall_clock_samples else 0.0,
        "peak_rss_kb": max(peak_rss_samples) if peak_rss_samples else None,
    }


def run_sql_support_benchmarks(base_root: str | Path) -> dict:
    """Generate and measure the SQL support benchmark corpora."""
    base_root = Path(base_root)
    sql_corpus_root = base_root / "sql_corpus"
    no_sql_root = base_root / "mixed_corpus_no_sql"
    with_sql_root = base_root / "mixed_corpus_with_sql_added"

    prepare_sql_corpus(sql_corpus_root)
    prepare_sql_benchmark_corpora(no_sql_root, with_sql_root)

    return {
        "sql_corpus": measure_corpus_runtime(sql_corpus_root, repeats=1),
        "mixed_corpus_no_sql": measure_corpus_runtime(no_sql_root, repeats=2),
        "mixed_corpus_with_sql_added": measure_corpus_runtime(with_sql_root, repeats=2),
    }


def run_benchmark(
    graph_path: str = "graphify-out/graph.json",
    corpus_words: int | None = None,
    questions: list[str] | None = None,
) -> dict:
    """Measure token reduction: corpus tokens vs graphify query tokens.

    Args:
        graph_path: path to the built graph
        corpus_words: total word count from detect() output; if None, estimated from graph
        questions: list of questions to benchmark; defaults to _SAMPLE_QUESTIONS

    Returns dict with: corpus_tokens, avg_query_tokens, reduction_ratio, per_question
    """
    data = json.loads(Path(graph_path).read_text(encoding="utf-8"))
    try:
        G = json_graph.node_link_graph(data, edges="links")
    except TypeError:
        G = json_graph.node_link_graph(data)

    if corpus_words is None:
        # Rough estimate: each node label is ~3 words, plus source context
        corpus_words = G.number_of_nodes() * 50

    corpus_tokens = corpus_words * 100 // 75  # words → tokens (100 words ≈ 133 tokens)

    qs = questions or _SAMPLE_QUESTIONS
    per_question = []
    for q in qs:
        qt = _query_subgraph_tokens(G, q)
        if qt > 0:
            per_question.append({"question": q, "query_tokens": qt, "reduction": round(corpus_tokens / qt, 1)})

    if not per_question:
        return {"error": "No matching nodes found for sample questions. Build the graph first."}

    avg_query_tokens = sum(p["query_tokens"] for p in per_question) // len(per_question)
    reduction_ratio = round(corpus_tokens / avg_query_tokens, 1) if avg_query_tokens > 0 else 0

    return {
        "corpus_tokens": corpus_tokens,
        "corpus_words": corpus_words,
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "avg_query_tokens": avg_query_tokens,
        "reduction_ratio": reduction_ratio,
        "per_question": per_question,
    }


def print_benchmark(result: dict) -> None:
    """Print a human-readable benchmark report."""
    if "error" in result:
        print(f"Benchmark error: {result['error']}")
        return

    print(f"\ngraphify token reduction benchmark")
    print(f"{'─' * 50}")
    print(f"  Corpus:          {result['corpus_words']:,} words → ~{result['corpus_tokens']:,} tokens (naive)")
    print(f"  Graph:           {result['nodes']:,} nodes, {result['edges']:,} edges")
    print(f"  Avg query cost:  ~{result['avg_query_tokens']:,} tokens")
    print(f"  Reduction:       {result['reduction_ratio']}x fewer tokens per query")
    print(f"\n  Per question:")
    for p in result["per_question"]:
        print(f"    [{p['reduction']}x] {p['question'][:55]}")
    print()
