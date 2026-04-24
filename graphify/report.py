# generate GRAPH_REPORT.md - the human-readable audit trail
from __future__ import annotations
import re
from datetime import date
import networkx as nx


def _safe_community_name(label: str) -> str:
    """Mirrors export.safe_name so community hub filenames and report wikilinks always agree."""
    cleaned = re.sub(r'[\\/*?:"<>|#^[\]]', "", label.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")).strip()
    cleaned = re.sub(r"\.(md|mdx|markdown)$", "", cleaned, flags=re.IGNORECASE)
    return cleaned or "unnamed"


def _render_sql_overview(G: nx.Graph) -> str | None:
    sql_files = [(node_id, data) for node_id, data in G.nodes(data=True) if data.get("type") == "sql_file"]
    if not sql_files:
        return None

    tables = {node_id: data for node_id, data in G.nodes(data=True) if data.get("type") == "table"}
    views = {
        node_id: data
        for node_id, data in G.nodes(data=True)
        if data.get("type") in {"view", "materialized_view"}
    }
    statements = [data for _, data in G.nodes(data=True) if data.get("type") == "statement"]
    default_schema = sorted(
        (data.get("default_schema", "public") for _, data in sql_files),
        key=lambda schema: (schema != "public", schema),
    )[0]

    referenced_rows = []
    for node_id, data in tables.items():
        selects = 0
        mutations = 0
        for _, _, edge in G.edges(data=True):
            target = edge.get("_tgt")
            if target != node_id:
                continue
            if edge.get("relation") in {"selects_from", "joins"}:
                selects += 1
            if edge.get("relation") in {"inserts_into", "updates", "deletes_from"}:
                mutations += 1
        referenced_rows.append((selects + mutations, data.get("qualified_name", data.get("label", node_id)), selects, mutations, data.get("defining_file") or "*(not found in corpus)*"))
    referenced_rows.sort(key=lambda item: (-item[0], item[1]))

    mutated_rows = []
    for node_id, data in tables.items():
        inserts = updates = deletes = 0
        for _, _, edge in G.edges(data=True):
            target = edge.get("_tgt")
            if target != node_id:
                continue
            relation = edge.get("relation")
            if relation == "inserts_into":
                inserts += 1
            elif relation == "updates":
                updates += 1
            elif relation == "deletes_from":
                deletes += 1
        total = inserts + updates + deletes
        mutated_rows.append((total, data.get("qualified_name", data.get("label", node_id)), inserts, updates, deletes))
    mutated_rows.sort(key=lambda item: (-item[0], item[1]))

    fan_in_rows = []
    for node_id, data in views.items():
        depends = sum(
            1
            for _, _, edge in G.edges(data=True)
            if edge.get("_src") == node_id and edge.get("relation") == "depends_on"
        )
        fan_in_rows.append((depends, data.get("qualified_name", data.get("label", node_id)), data.get("defining_file") or "*(not found in corpus)*"))
    fan_in_rows.sort(key=lambda item: (-item[0], item[1]))

    hotspot_rows = []
    for _, data in sql_files:
        hotspot_rows.append((data.get("statement_count", 0), data.get("label", data.get("path", "")), len({
            edge.get("_tgt")
            for _, _, edge in G.edges(data=True)
            if edge.get("_src") == data.get("id")
            if edge.get("relation") == "defines"
        })))
    hotspot_rows.sort(key=lambda item: (-item[0], item[1]))

    def render_table(header: str, rows: list[tuple], format_row) -> list[str]:
        lines = [header]
        visible = rows[:10]
        lines.extend(format_row(row) for row in visible)
        if len(rows) > 10:
            lines.append("")
            lines.append(f"(and {len(rows) - 10} more)")
        return lines

    lines = [
        "## SQL Overview",
        "",
        f"_{len(statements)} statements across {len(sql_files)} .sql files. Default schema: `{default_schema}`._",
        "",
        "### Most-referenced tables",
        "",
        "| Table | Selects | Mutations | Defined in |",
        "|---|---:|---:|---|",
    ]
    for _, qualified_name, selects, mutations, defining_file in referenced_rows[:10]:
        lines.append(f"| `{qualified_name}` | {selects} | {mutations} | `{defining_file}` |")
    if len(referenced_rows) > 10:
        lines.extend(["", f"(and {len(referenced_rows) - 10} more)"])

    lines.extend([
        "",
        "### Most-mutated tables",
        "",
        "| Table | Inserts | Updates | Deletes | Total |",
        "|---|---:|---:|---:|---:|",
    ])
    for total, qualified_name, inserts, updates, deletes in mutated_rows[:10]:
        lines.append(f"| `{qualified_name}` | {inserts} | {updates} | {deletes} | {total} |")
    if len(mutated_rows) > 10:
        lines.extend(["", f"(and {len(mutated_rows) - 10} more)"])

    lines.extend([
        "",
        "### Views by dependency fan-in",
        "",
        "| View | Depends on | Defined in |",
        "|---|---:|---|",
    ])
    for depends, qualified_name, defining_file in fan_in_rows[:10]:
        lines.append(f"| `{qualified_name}` | {depends} tables | `{defining_file}` |")
    if len(fan_in_rows) > 10:
        lines.extend(["", f"(and {len(fan_in_rows) - 10} more)"])

    lines.extend([
        "",
        "### SQL hotspots by file",
        "",
        "| File | Statements | Tables referenced |",
        "|---|---:|---:|",
    ])
    for statement_count, label, table_refs in hotspot_rows[:10]:
        lines.append(f"| `{label}` | {statement_count} | {table_refs} |")
    if len(hotspot_rows) > 10:
        lines.extend(["", f"(and {len(hotspot_rows) - 10} more)"])

    return "\n".join(lines)


def generate(
    G: nx.Graph,
    communities: dict[int, list[str]],
    cohesion_scores: dict[int, float],
    community_labels: dict[int, str],
    god_node_list: list[dict],
    surprise_list: list[dict],
    detection_result: dict,
    token_cost: dict,
    root: str,
    suggested_questions: list[dict] | None = None,
) -> str:
    today = date.today().isoformat()

    confidences = [d.get("confidence", "EXTRACTED") for _, _, d in G.edges(data=True)]
    total = len(confidences) or 1
    ext_pct = round(confidences.count("EXTRACTED") / total * 100)
    inf_pct = round(confidences.count("INFERRED") / total * 100)
    amb_pct = round(confidences.count("AMBIGUOUS") / total * 100)

    inf_edges = [(u, v, d) for u, v, d in G.edges(data=True) if d.get("confidence") == "INFERRED"]
    inf_scores = [d.get("confidence_score", 0.5) for _, _, d in inf_edges]
    inf_avg = round(sum(inf_scores) / len(inf_scores), 2) if inf_scores else None

    lines = [
        f"# Graph Report - {root}  ({today})",
        "",
        "## Corpus Check",
    ]
    if detection_result.get("warning"):
        lines.append(f"- {detection_result['warning']}")
    else:
        lines += [
            f"- {detection_result['total_files']} files · ~{detection_result['total_words']:,} words",
            "- Verdict: corpus is large enough that graph structure adds value.",
        ]

    from .analyze import _is_file_node as _ifn
    non_empty = {cid: nodes for cid, nodes in communities.items()
                 if any(not _ifn(G, n) for n in nodes)}

    lines += [
        "",
        "## Summary",
        f"- {G.number_of_nodes()} nodes · {G.number_of_edges()} edges · {len(non_empty)} communities detected",
        f"- Extraction: {ext_pct}% EXTRACTED · {inf_pct}% INFERRED · {amb_pct}% AMBIGUOUS"
        + (f" · INFERRED: {len(inf_edges)} edges (avg confidence: {inf_avg})" if inf_avg is not None else ""),
        f"- Token cost: {token_cost.get('input', 0):,} input · {token_cost.get('output', 0):,} output",
    ]

    # Community hub navigation - links to _COMMUNITY_*.md files in the Obsidian vault.
    # Without these, GRAPH_REPORT.md is a dead-end and the vault splits into disconnected components.
    if non_empty:
        lines += ["", "## Community Hubs (Navigation)"]
        for cid in non_empty:
            label = community_labels.get(cid, f"Community {cid}")
            safe = _safe_community_name(label)
            lines.append(f"- [[_COMMUNITY_{safe}|{label}]]")

    lines += [
        "",
        "## God Nodes (most connected - your core abstractions)",
    ]
    for i, node in enumerate(god_node_list, 1):
        lines.append(f"{i}. `{node['label']}` - {node['degree']} edges")

    sql_overview = _render_sql_overview(G)
    if sql_overview:
        lines += ["", sql_overview]

    lines += ["", "## Surprising Connections (you probably didn't know these)"]
    if surprise_list:
        for s in surprise_list:
            relation = s.get("relation", "related_to")
            note = s.get("note", "")
            files = s.get("source_files", ["", ""])
            conf = s.get("confidence", "EXTRACTED")
            cscore = s.get("confidence_score")
            if conf == "INFERRED" and cscore is not None:
                conf_tag = f"INFERRED {cscore:.2f}"
            else:
                conf_tag = conf
            sem_tag = " [semantically similar]" if relation == "semantically_similar_to" else ""
            lines += [
                f"- `{s['source']}` --{relation}--> `{s['target']}`  [{conf_tag}]{sem_tag}",
                f"  {files[0]} → {files[1]}" + (f"  _{note}_" if note else ""),
            ]
    else:
        lines.append("- None detected - all connections are within the same source files.")

    hyperedges = G.graph.get("hyperedges", [])
    if hyperedges:
        lines += ["", "## Hyperedges (group relationships)"]
        for h in hyperedges:
            node_labels = ", ".join(h.get("nodes", []))
            conf = h.get("confidence", "INFERRED")
            cscore = h.get("confidence_score")
            conf_tag = f"{conf} {cscore:.2f}" if cscore is not None else conf
            lines.append(f"- **{h.get('label', h.get('id', ''))}** — {node_labels} [{conf_tag}]")

    lines += ["", "## Communities"]
    for cid, nodes in communities.items():
        label = community_labels.get(cid, f"Community {cid}")
        score = cohesion_scores.get(cid, 0.0)
        # Filter method/function stubs from display - they're structural noise
        real_nodes = [n for n in nodes if not _ifn(G, n)]
        if not real_nodes:
            continue
        display = [G.nodes[n].get("label", n) for n in real_nodes[:8]]
        suffix = f" (+{len(real_nodes)-8} more)" if len(real_nodes) > 8 else ""
        lines += [
            "",
            f"### Community {cid} - \"{label}\"",
            f"Cohesion: {score}",
            f"Nodes ({len(real_nodes)}): {', '.join(display)}{suffix}",
        ]

    ambiguous = [(u, v, d) for u, v, d in G.edges(data=True) if d.get("confidence") == "AMBIGUOUS"]
    if ambiguous:
        lines += ["", "## Ambiguous Edges - Review These"]
        for u, v, d in ambiguous:
            ul = G.nodes[u].get("label", u)
            vl = G.nodes[v].get("label", v)
            lines += [
                f"- `{ul}` → `{vl}`  [AMBIGUOUS]",
                f"  {d.get('source_file', '')} · relation: {d.get('relation', 'unknown')}",
            ]

    # --- Gaps section ---
    from .analyze import _is_file_node, _is_concept_node

    isolated = [
        n for n in G.nodes()
        if G.degree(n) <= 1 and not _is_file_node(G, n) and not _is_concept_node(G, n)
    ]
    thin_communities = {
        cid: nodes for cid, nodes in communities.items()
        if 0 < sum(1 for n in nodes if not _is_file_node(G, n)) < 3
    }
    gap_count = len(isolated) + len(thin_communities)

    if gap_count > 0 or amb_pct > 20:
        lines += ["", "## Knowledge Gaps"]
        if isolated:
            isolated_labels = [G.nodes[n].get("label", n) for n in isolated[:5]]
            suffix = f" (+{len(isolated)-5} more)" if len(isolated) > 5 else ""
            lines.append(f"- **{len(isolated)} isolated node(s):** {', '.join(f'`{l}`' for l in isolated_labels)}{suffix}")
            lines.append("  These have ≤1 connection - possible missing edges or undocumented components.")
        if thin_communities:
            for cid, nodes in thin_communities.items():
                label = community_labels.get(cid, f"Community {cid}")
                node_labels = [G.nodes[n].get("label", n) for n in nodes]
                lines.append(f"- **Thin community `{label}`** ({len(nodes)} nodes): {', '.join(f'`{l}`' for l in node_labels)}")
                lines.append("  Too small to be a meaningful cluster - may be noise or needs more connections extracted.")
        if amb_pct > 20:
            lines.append(f"- **High ambiguity: {amb_pct}% of edges are AMBIGUOUS.** Review the Ambiguous Edges section above.")

    if suggested_questions:
        lines += ["", "## Suggested Questions"]
        no_signal = len(suggested_questions) == 1 and suggested_questions[0].get("type") == "no_signal"
        if no_signal:
            lines.append(f"_{suggested_questions[0]['why']}_")
        else:
            lines.append("_Questions this graph is uniquely positioned to answer:_")
            lines.append("")
            for q in suggested_questions:
                if q.get("question"):
                    lines.append(f"- **{q['question']}**")
                    lines.append(f"  _{q['why']}_")

    return "\n".join(lines)
