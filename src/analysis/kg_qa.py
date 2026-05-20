"""Objective 1 closing task: KG quality assurance and summary statistics.

Runs integrity checks on the Neo4j KG and generates descriptive statistics
for the paper, Zenodo data descriptor, and embeddings evaluation baseline.

Outputs:
  - Console report
  - docs/objective1_kg_qa_report.md (paper-ready markdown)

Usage:
    python src/analysis/kg_qa.py
"""
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

REPORT_PATH = PROJECT_ROOT / "docs" / "objective1_kg_qa_report.md"

# Schema for the 9 core predicates (curated-only types checked separately)
PREDICATE_TYPES = {
    # Expanded schema (refined during QA): modulation predicates accept
    # Food, Bioactive, or Microbe subjects, reflecting biological reality
    # that bioactives and microbes also modulate abundance and markers.
    "CONTAINS":                   ({"Food"}, {"Bioactive"}),
    "PRODUCES":                   ({"Microbe"}, {"Bioactive"}),
    "INCREASES_ABUNDANCE_OF":     ({"Food", "Bioactive", "Microbe"}, {"Microbe"}),
    "DECREASES_ABUNDANCE_OF":     ({"Food", "Bioactive", "Microbe"}, {"Microbe"}),
    "INCREASED_IN":               ({"Microbe"}, {"IBD_Outcome"}),
    "DECREASED_IN":               ({"Microbe"}, {"IBD_Outcome"}),
    "INCREASES_MARKER":           ({"Food", "Bioactive", "Microbe"}, {"IBD_Outcome"}),
    "DECREASES_MARKER":           ({"Food", "Bioactive", "Microbe"}, {"IBD_Outcome"}),
    "HAS_HIGH_FODMAP_CONTENT_OF": ({"Food"}, {"Bioactive"}),
}

# Output collector — accumulates lines for both console + markdown file
report_lines = []


def emit(line=""):
    """Print to console and collect for the markdown report."""
    print(line)
    report_lines.append(line)


def get_driver():
    return GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD")),
    )


def section(title):
    emit()
    emit(f"## {title}")
    emit()


def main():
    driver = get_driver()

    emit(f"# DietIBD-KG — Objective 1 QA & Summary Statistics")
    emit()
    emit(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    with driver.session() as s:

        # ─────────────────────────────────────────────────────────
        section("1. Overview")
        n_nodes = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        n_edges = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        emit(f"- **Total nodes:** {n_nodes:,}")
        emit(f"- **Total edges:** {n_edges:,}")

        uniq = s.run("""
            MATCH (a)-[r]->(b)
            WITH a.id AS sub, type(r) AS pred, b.id AS obj
            RETURN count(DISTINCT [sub, pred, obj]) AS uniq, count(*) AS total
        """).single()
        emit(f"- **Unique (subject, predicate, object) triples:** {uniq['uniq']:,}")
        emit(f"- **Total edges (with evidence multiplicity):** {uniq['total']:,}")
        dup_factor = uniq['total'] / uniq['uniq'] if uniq['uniq'] else 0
        emit(f"- **Evidence multiplicity factor:** {dup_factor:.2f} "
             f"(edges per unique triple — LLM triples reported by multiple papers)")

        # ─────────────────────────────────────────────────────────
        section("2. Integrity Checks")

        checks = []

        # 2a. Orphan nodes
        orphans = s.run("MATCH (n) WHERE NOT (n)--() RETURN count(n) AS c").single()["c"]
        checks.append(("Orphan nodes (degree 0)", orphans,
                       "PASS" if orphans == 0 else "WARN"))

        # 2b. Self-loops
        loops = s.run("MATCH (n)-[r]->(n) RETURN count(r) AS c").single()["c"]
        checks.append(("Self-loop edges", loops,
                       "PASS" if loops == 0 else "WARN"))

        # 2c. Nodes missing core properties
        bad_nodes = s.run("""
            MATCH (n) WHERE n.id IS NULL OR n.label IS NULL
            RETURN count(n) AS c
        """).single()["c"]
        checks.append(("Nodes missing id/label", bad_nodes,
                       "PASS" if bad_nodes == 0 else "FAIL"))

        # 2d. Edges missing provenance
        bad_edges = s.run("""
            MATCH ()-[r]->() WHERE r.sources IS NULL
            RETURN count(r) AS c
        """).single()["c"]
        checks.append(("Edges missing sources property", bad_edges,
                       "PASS" if bad_edges == 0 else "WARN"))

        # 2e. LLM edges missing PMID
        llm_no_pmid = s.run("""
            MATCH ()-[r]->()
            WHERE 'LLM' IN r.sources AND r.evidence_pmid IS NULL
            RETURN count(r) AS c
        """).single()["c"]
        checks.append(("LLM edges missing evidence_pmid", llm_no_pmid,
                       "PASS" if llm_no_pmid == 0 else "WARN"))

        # 2f. Duplicate node IDs
        dup_ids = s.run("""
            MATCH (n) WHERE n.id IS NOT NULL
            WITH n.id AS id, count(*) AS c WHERE c > 1
            RETURN count(*) AS c
        """).single()["c"]
        checks.append(("Duplicate node IDs", dup_ids,
                       "PASS" if dup_ids == 0 else "FAIL"))

        emit("| Check | Count | Status |")
        emit("|---|---|---|")
        for name, count, status in checks:
            emit(f"| {name} | {count:,} | {status} |")

        # ─────────────────────────────────────────────────────────
        section("3. Schema Validation")
        emit("Edge endpoint types vs expected schema (9 core predicates):")
        emit()
        emit("| Relationship | Expected | Observed (subject -> object) | Violations |")
        emit("|---|---|---|---|")
        total_violations = 0
        for rel_type, (exp_sub, exp_obj) in PREDICATE_TYPES.items():
            rows = s.run(f"""
                MATCH (a)-[r:`{rel_type}`]->(b)
                RETURN labels(a)[0] AS sub, labels(b)[0] AS obj, count(*) AS c
                ORDER BY c DESC
            """).data()
            exp_str = f"{{{'|'.join(sorted(exp_sub))}}} -> {{{'|'.join(sorted(exp_obj))}}}"
            if not rows:
                emit(f"| {rel_type} | {exp_str} | (none) | 0 |")
                continue
            observed = ", ".join(f"{r['sub']}->{r['obj']} ({r['c']})" for r in rows)
            viol = sum(r["c"] for r in rows
                       if r["sub"] not in exp_sub or r["obj"] not in exp_obj)
            total_violations += viol
            emit(f"| {rel_type} | {exp_str} | {observed} | {viol} |")
        emit()
        emit(f"**Total schema violations across core predicates: {total_violations}**")

        # Curated-only relationship types (no fixed schema asserted)
        emit()
        emit("Curated-only relationship types (endpoint distribution, informational):")
        emit()
        emit("| Relationship | Endpoint types |")
        emit("|---|---|")
        for rel_type in ["INVOLVES", "IS_LOW_FODMAP_FOOD", "MODULATES_CLUSTER"]:
            rows = s.run(f"""
                MATCH (a)-[r:`{rel_type}`]->(b)
                RETURN labels(a)[0] AS sub, labels(b)[0] AS obj, count(*) AS c
                ORDER BY c DESC
            """).data()
            if rows:
                obs = ", ".join(f"{r['sub']}->{r['obj']} ({r['c']})" for r in rows)
                emit(f"| {rel_type} | {obs} |")

        # ─────────────────────────────────────────────────────────
        section("4. Node Statistics")
        emit("| Node type | Count | % of nodes |")
        emit("|---|---|---|")
        node_rows = s.run("""
            MATCH (n) UNWIND labels(n) AS l
            RETURN l AS type, count(*) AS c ORDER BY c DESC
        """).data()
        for r in node_rows:
            emit(f"| {r['type']} | {r['c']:,} | {r['c']/n_nodes*100:.1f}% |")

        # New (LLM-created) vs pre-existing (curated) nodes
        llm_nodes = s.run("""
            MATCH (n) WHERE n.source = 'LLM' RETURN count(n) AS c
        """).single()["c"]
        emit()
        emit(f"- **Curated (pre-existing) nodes:** {n_nodes - llm_nodes:,}")
        emit(f"- **LLM-introduced nodes:** {llm_nodes:,}")

        # ─────────────────────────────────────────────────────────
        section("5. Edge Statistics by Relationship Type")
        emit("| Relationship | Total | Curated | LLM |")
        emit("|---|---|---|---|")
        edge_rows = s.run("""
            MATCH ()-[r]->()
            WITH type(r) AS rt,
                 CASE WHEN 'LLM' IN r.sources THEN 'LLM' ELSE 'curated' END AS src
            RETURN rt, src, count(*) AS c
        """).data()
        by_rt = defaultdict(lambda: {"curated": 0, "LLM": 0})
        for r in edge_rows:
            by_rt[r["rt"]][r["src"]] += r["c"]
        for rt in sorted(by_rt, key=lambda k: -sum(by_rt[k].values())):
            c = by_rt[rt]
            emit(f"| {rt} | {c['curated']+c['LLM']:,} | {c['curated']:,} | {c['LLM']:,} |")

        # ─────────────────────────────────────────────────────────
        section("6. Provenance & Evidence")
        prov = s.run("""
            MATCH ()-[r]->()
            WITH CASE WHEN 'LLM' IN r.sources THEN 'LLM' ELSE 'curated' END AS src
            RETURN src, count(*) AS c
        """).data()
        emit("| Source | Edges | % |")
        emit("|---|---|---|")
        for r in prov:
            emit(f"| {r['src']} | {r['c']:,} | {r['c']/n_edges*100:.1f}% |")

        # Source database breakdown (curated edges may list multiple sources)
        emit()
        emit("Edges per source label (sources property unwound):")
        emit()
        emit("| Source label | Edges |")
        emit("|---|---|")
        for r in s.run("""
            MATCH ()-[r]->() UNWIND r.sources AS src
            RETURN src, count(*) AS c ORDER BY c DESC
        """).data():
            emit(f"| {r['src']} | {r['c']:,} |")

        # LLM confidence distribution
        conf = s.run("""
            MATCH ()-[r]->() WHERE 'LLM' IN r.sources AND r.confidence IS NOT NULL
            RETURN min(r.confidence) AS mn, max(r.confidence) AS mx,
                   avg(r.confidence) AS mean,
                   percentileCont(r.confidence, 0.25) AS q1,
                   percentileCont(r.confidence, 0.5) AS med,
                   percentileCont(r.confidence, 0.75) AS q3
        """).single()
        emit()
        emit("LLM edge confidence distribution:")
        emit()
        emit(f"- min={conf['mn']:.2f}, Q1={conf['q1']:.2f}, median={conf['med']:.2f}, "
             f"Q3={conf['q3']:.2f}, max={conf['mx']:.2f}, mean={conf['mean']:.3f}")

        # Evidence type breakdown
        emit()
        emit("LLM edge evidence types:")
        emit()
        emit("| Evidence type | Edges |")
        emit("|---|---|")
        for r in s.run("""
            MATCH ()-[r]->() WHERE 'LLM' IN r.sources
            RETURN r.evidence_type AS et, count(*) AS c ORDER BY c DESC
        """).data():
            emit(f"| {r['et']} | {r['c']:,} |")

        # Unique PMIDs cited
        pmids = s.run("""
            MATCH ()-[r]->() WHERE 'LLM' IN r.sources AND r.evidence_pmid IS NOT NULL
            RETURN count(DISTINCT r.evidence_pmid) AS c
        """).single()["c"]
        emit()
        emit(f"- **Unique PubMed IDs cited across LLM edges:** {pmids:,}")

        # ─────────────────────────────────────────────────────────
        section("7. Graph Topology")
        deg = s.run("""
            MATCH (n)
            OPTIONAL MATCH (n)-[r]-()
            WITH n, count(r) AS d
            RETURN min(d) AS mn, max(d) AS mx, avg(d) AS mean,
                   percentileCont(d, 0.5) AS med,
                   percentileCont(d, 0.9) AS p90
        """).single()
        emit("Degree distribution (undirected, all node types):")
        emit()
        emit(f"- min={deg['mn']}, median={deg['med']:.0f}, mean={deg['mean']:.1f}, "
             f"p90={deg['p90']:.0f}, max={deg['mx']}")

        emit()
        emit("Degree by node type:")
        emit()
        emit("| Node type | Nodes | Mean degree | Max degree |")
        emit("|---|---|---|---|")
        for r in s.run("""
            MATCH (n)
            OPTIONAL MATCH (n)-[rel]-()
            WITH n, labels(n)[0] AS t, count(rel) AS d
            RETURN t, count(n) AS nn, avg(d) AS avgd, max(d) AS maxd
            ORDER BY avgd DESC
        """).data():
            emit(f"| {r['t']} | {r['nn']:,} | {r['avgd']:.1f} | {r['maxd']} |")

        emit()
        emit("Top 15 hub entities (highest degree):")
        emit()
        emit("| Rank | Type | Entity | Degree |")
        emit("|---|---|---|---|")
        for i, r in enumerate(s.run("""
            MATCH (n)-[rel]-()
            WITH n, count(rel) AS d
            RETURN labels(n)[0] AS t, n.label AS lbl, d
            ORDER BY d DESC LIMIT 15
        """).data(), 1):
            emit(f"| {i} | {r['t']} | {r['lbl']} | {r['d']} |")

        # Connected components — compute in Python (no GDS/APOC)
        emit()
        edges = s.run("""
            MATCH (a)-[r]->(b) RETURN a.id AS s, b.id AS o
        """).data()
        all_node_ids = set(
            x["id"] for x in s.run("MATCH (n) RETURN n.id AS id").data()
        )

    driver.close()

    # Union-find for connected components
    parent = {nid: nid for nid in all_node_ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for e in edges:
        if e["s"] in parent and e["o"] in parent:
            union(e["s"], e["o"])

    comps = Counter(find(nid) for nid in all_node_ids)
    comp_sizes = sorted(comps.values(), reverse=True)

    emit("Connected components (treating edges as undirected):")
    emit()
    emit(f"- **Number of components:** {len(comp_sizes):,}")
    emit(f"- **Largest component:** {comp_sizes[0]:,} nodes "
         f"({comp_sizes[0]/len(all_node_ids)*100:.1f}% of graph)")
    if len(comp_sizes) > 1:
        singletons = sum(1 for x in comp_sizes if x == 1)
        emit(f"- **Singleton components:** {singletons:,}")
        emit(f"- **Component size distribution (top 10):** {comp_sizes[:10]}")

    # ─────────────────────────────────────────────────────────
    section("8. Summary for Paper")
    emit("Headline numbers for the manuscript Results section:")
    emit()
    emit(f"- DietIBD-KG comprises {n_nodes:,} nodes and {n_edges:,} edges")
    emit(f"- {uniq['uniq']:,} unique diet-microbiome-IBD relationships")
    emit(f"- Dual provenance: curated databases + LLM-extracted literature")
    emit(f"- {pmids:,} PubMed articles cited as edge-level evidence")
    emit(f"- Largest connected component covers "
         f"{comp_sizes[0]/len(all_node_ids)*100:.1f}% of all nodes")
    emit(f"- {total_violations} schema violations among core predicates")

    # Write the markdown report
    REPORT_PATH.write_text("\n".join(report_lines), encoding="utf-8")
    print()
    print(f"=== Report written to {REPORT_PATH} ===")


if __name__ == "__main__":
    main()
