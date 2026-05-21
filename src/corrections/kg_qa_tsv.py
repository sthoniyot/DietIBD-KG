#!/usr/bin/env python3
"""DietIBD-KG -- standalone QA & summary statistics for the corrected graph.

This is a TSV-based re-implementation of src/analysis/kg_qa.py. The original
kg_qa.py reads the graph from Neo4j; the entity-typing correction was applied
to the release TSV files, so this script runs the same integrity checks and
descriptive statistics directly on the corrected node/edge tables -- no Neo4j
reload required.

Inputs (tab-separated, with header row):
  nodes : id, label, type, origin
  edges : subject_id, subject_label, predicate, object_id, object_label,
          sources, confidence, evidence_count, evidence_types,
          evidence_pmid, evidence_type, evidence_span

Outputs:
  - console report
  - <REPORT_PATH> (paper-ready markdown)

Usage:
    Run from the repository root:
        python kg_qa_tsv.py
"""
import csv
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# -- Configuration -- paths are relative to the current directory, so run
#    this script from the repository root (or edit the paths below). --------
NODES_PATH = Path("corrections/nodes_corrected.tsv")
EDGES_PATH = Path("corrections/edges_corrected.tsv")
REPORT_PATH = Path("docs/objective1_kg_qa_report_corrected.md")

# Schema for the 9 core predicates -- copied verbatim from the PREDICATE_TYPES
# dict in src/analysis/kg_qa.py: (allowed subject types, allowed object types).
CORE_PREDICATE_TYPES = {
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

# Curated-only predicates -- checked separately, as in kg_qa.py.
CURATED_PREDICATE_TYPES = {
    "INVOLVES":           ({"Pathway"}, {"Bioactive"}),
    "IS_LOW_FODMAP_FOOD": ({"Food"},    {"Bioactive"}),
    "MODULATES_CLUSTER":  ({"Food"},    {"Microbe"}),
}

# An edge whose `sources` value equals this is literature-derived; every
# other value (FooDB, KEGG, Disbiome, Bolte2021, FODMAP_consensus) is curated.
LITERATURE_SOURCE = "LLM"

# -- Report collector ------------------------------------------------------
report_lines = []


def emit(line=""):
    """Print to console and collect for the markdown report."""
    print(line)
    report_lines.append(line)


def section(title):
    emit()
    emit(f"## {title}")
    emit()


def pct(n, total):
    return f"{(100.0 * n / total):.1f}%" if total else "0.0%"


# -- Loaders ---------------------------------------------------------------
def load_nodes(path):
    if not path.exists():
        sys.exit(f"ERROR: nodes file not found: {path}\n"
                 f"Run this script from the repository root.")
    nodes, dup_ids = {}, []
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        missing = {"id", "label", "type", "origin"} - set(reader.fieldnames or [])
        if missing:
            sys.exit(f"ERROR: nodes file missing columns: {sorted(missing)}")
        for row in reader:
            nid = (row["id"] or "").strip()
            if not nid:
                continue
            if nid in nodes:
                dup_ids.append(nid)
            nodes[nid] = {
                "label":  (row["label"] or "").strip(),
                "type":   (row["type"] or "").strip(),
                "origin": (row["origin"] or "").strip(),
            }
    return nodes, dup_ids


def load_edges(path):
    if not path.exists():
        sys.exit(f"ERROR: edges file not found: {path}\n"
                 f"Run this script from the repository root.")
    edges = []
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        required = {"subject_id", "predicate", "object_id", "sources",
                    "confidence", "evidence_count", "evidence_type",
                    "evidence_pmid"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            sys.exit(f"ERROR: edges file missing columns: {sorted(missing)}")
        for row in reader:
            edges.append({
                "s":        (row["subject_id"] or "").strip(),
                "p":        (row["predicate"] or "").strip(),
                "o":        (row["object_id"] or "").strip(),
                "sources":  (row["sources"] or "").strip(),
                "conf":     (row["confidence"] or "").strip(),
                "ev_count": (row["evidence_count"] or "").strip(),
                "ev_type":  (row["evidence_type"] or "").strip(),
                "pmid":     (row["evidence_pmid"] or "").strip(),
            })
    return edges


# -- Main ------------------------------------------------------------------
def main():
    emit("# DietIBD-KG -- QA & Summary Statistics (corrected graph)")
    emit()
    emit(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    emit()
    emit(f"Source files: `{NODES_PATH}`, `{EDGES_PATH}`")

    nodes, dup_ids = load_nodes(NODES_PATH)
    edges = load_edges(EDGES_PATH)
    if not nodes:
        sys.exit("ERROR: node table is empty.")

    def is_lit(e):
        return e["sources"] == LITERATURE_SOURCE

    # -- 1. Overview -------------------------------------------------------
    section("1. Overview")
    n_nodes = len(nodes)
    n_edges = len(edges)
    triples = {(e["s"], e["p"], e["o"]) for e in edges}
    n_triples = len(triples)
    mult = n_edges / n_triples if n_triples else 0.0
    emit(f"- **Total entities:** {n_nodes:,}")
    emit(f"- **Total edges:** {n_edges:,}")
    emit(f"- **Unique triples (subject, predicate, object):** {n_triples:,}")
    emit(f"- **Edge multiplicity:** {mult:.2f} edges per unique triple")

    # -- 2. Entity types ---------------------------------------------------
    section("2. Entity types")
    type_counts = Counter(n["type"] for n in nodes.values())
    emit("| Type | Count | % of entities |")
    emit("|------|------:|--------------:|")
    for t, c in type_counts.most_common():
        emit(f"| {t or '(blank)'} | {c:,} | {pct(c, n_nodes)} |")
    emit(f"| **Total** | **{n_nodes:,}** | **100.0%** |")
    emit()
    origin_counts = Counter(n["origin"] for n in nodes.values())
    emit("Entities by origin:")
    emit()
    for o, c in origin_counts.most_common():
        emit(f"- **{o or '(blank)'}:** {c:,} ({pct(c, n_nodes)})")
    emit()
    origins = sorted(origin_counts)
    cross = defaultdict(Counter)
    for n in nodes.values():
        cross[n["type"]][n["origin"]] += 1
    emit("Entity type x origin:")
    emit()
    emit("| Type | " + " | ".join(origins) + " |")
    emit("|------|" + "|".join("---:" for _ in origins) + "|")
    for t, _ in type_counts.most_common():
        cells = " | ".join(f"{cross[t][o]:,}" for o in origins)
        emit(f"| {t or '(blank)'} | {cells} |")

    # -- 3. Edge predicates ------------------------------------------------
    section("3. Edge types (predicates)")
    pred_counts = Counter(e["p"] for e in edges)
    pred_lit = Counter(e["p"] for e in edges if is_lit(e))
    pred_cur = Counter(e["p"] for e in edges if not is_lit(e))
    emit("| Predicate | Total | Curated | Literature |")
    emit("|-----------|------:|--------:|-----------:|")
    for p, c in pred_counts.most_common():
        emit(f"| {p} | {c:,} | {pred_cur[p]:,} | {pred_lit[p]:,} |")
    emit(f"| **Total** | **{n_edges:,}** | **{sum(pred_cur.values()):,}** "
         f"| **{sum(pred_lit.values()):,}** |")

    # -- 4. Provenance -----------------------------------------------------
    section("4. Provenance")
    src_counts = Counter(e["sources"] for e in edges)
    emit("Edges by source:")
    emit()
    emit("| Source | Edges | % |")
    emit("|--------|------:|--:|")
    for s, c in src_counts.most_common():
        emit(f"| {s or '(blank)'} | {c:,} | {pct(c, n_edges)} |")
    emit()
    n_lit = sum(1 for e in edges if is_lit(e))
    n_cur = n_edges - n_lit
    emit(f"- **Curated edges:** {n_cur:,} ({pct(n_cur, n_edges)})")
    emit(f"- **Literature edges:** {n_lit:,} ({pct(n_lit, n_edges)})")
    pmids = {e["pmid"] for e in edges if e["pmid"]}
    emit(f"- **Distinct PubMed IDs cited as edge evidence:** {len(pmids):,}")
    ev_total = 0
    for e in edges:
        try:
            ev_total += int(e["ev_count"])
        except ValueError:
            pass
    emit(f"- **Total evidence records (sum of evidence_count):** {ev_total:,}")

    # -- 5. Confidence -----------------------------------------------------
    section("5. Confidence scores")

    def conf_vals(subset):
        out = []
        for e in subset:
            try:
                out.append(float(e["conf"]))
            except ValueError:
                pass
        return out

    def describe(vals):
        if not vals:
            return "n/a"
        return (f"min {min(vals):.2f}, max {max(vals):.2f}, "
                f"mean {statistics.mean(vals):.3f}, "
                f"median {statistics.median(vals):.2f}")

    emit(f"- **Literature edges:** "
         f"{describe(conf_vals([e for e in edges if is_lit(e)]))}")
    emit(f"- **Curated edges:** "
         f"{describe(conf_vals([e for e in edges if not is_lit(e)]))}")

    # -- 6. Study-design profile ------------------------------------------
    section("6. Study-design profile (literature edges)")
    design = Counter(e["ev_type"] for e in edges if is_lit(e))
    lit_total = sum(design.values())
    emit("| Study design | Edges | % of literature edges |")
    emit("|--------------|------:|----------------------:|")
    for d, c in design.most_common():
        emit(f"| {d or '(unlabelled)'} | {c:,} | {pct(c, lit_total)} |")

    # -- 7. Schema validation ---------------------------------------------
    section("7. Schema validation")
    core_violations, curated_violations = [], []
    unknown_pred = Counter()
    dangling = []
    for e in edges:
        s_node, o_node = nodes.get(e["s"]), nodes.get(e["o"])
        if s_node is None or o_node is None:
            dangling.append(e)
            continue
        st, ot, p = s_node["type"], o_node["type"], e["p"]
        if p in CORE_PREDICATE_TYPES:
            allow_s, allow_o = CORE_PREDICATE_TYPES[p]
            if st not in allow_s or ot not in allow_o:
                core_violations.append((e, st, ot))
        elif p in CURATED_PREDICATE_TYPES:
            allow_s, allow_o = CURATED_PREDICATE_TYPES[p]
            if st not in allow_s or ot not in allow_o:
                curated_violations.append((e, st, ot))
        else:
            unknown_pred[p] += 1

    emit(f"Checked {n_edges:,} edges against the schema "
         f"({len(CORE_PREDICATE_TYPES)} core predicates, "
         f"{len(CURATED_PREDICATE_TYPES)} curated-only predicates).")
    emit()
    emit(f"- **Core-predicate schema violations:** {len(core_violations)}")
    emit(f"- **Curated-predicate schema violations:** {len(curated_violations)}")
    if unknown_pred:
        detail = ", ".join(f"{p} x{c}" for p, c in unknown_pred.most_common())
        emit(f"- **Edges with unrecognised predicate:** "
             f"{sum(unknown_pred.values())} ({detail})")
    else:
        emit("- **Edges with unrecognised predicate:** 0")
    emit(f"- **Dangling edges (endpoint missing from node table):** "
         f"{len(dangling)}")
    emit()
    if not core_violations and not curated_violations:
        emit("**Verdict: PASS -- no schema violations.**")
    else:
        emit("**Verdict: FAIL -- schema violations present:**")
        emit()
        shown = core_violations + curated_violations
        for e, st, ot in shown[:50]:
            emit(f"  - {e['s']} ({st or 'no-type'}) "
                 f"-[{e['p']}]-> {e['o']} ({ot or 'no-type'})")
        if len(shown) > 50:
            emit(f"  - ... and {len(shown) - 50} more")

    # -- 8. Topology -------------------------------------------------------
    section("8. Topology")
    in_deg, out_deg = Counter(), Counter()
    for e in edges:
        if e["s"] in nodes:
            out_deg[e["s"]] += 1
        if e["o"] in nodes:
            in_deg[e["o"]] += 1
    total_deg = {nid: in_deg[nid] + out_deg[nid] for nid in nodes}
    deg_vals = list(total_deg.values())
    orphans = [nid for nid, d in total_deg.items() if d == 0]
    emit(f"- **Mean degree:** {statistics.mean(deg_vals):.2f}")
    emit(f"- **Median degree:** {statistics.median(deg_vals):.1f}")
    emit(f"- **Max degree:** {max(deg_vals):,}")
    emit(f"- **Orphan entities (degree 0):** {len(orphans):,}")
    emit()
    emit("Mean degree by entity type:")
    emit()
    by_type_deg = defaultdict(list)
    for nid, n in nodes.items():
        by_type_deg[n["type"]].append(total_deg[nid])
    for t, _ in type_counts.most_common():
        vals = by_type_deg[t]
        emit(f"- **{t or '(blank)'}:** mean {statistics.mean(vals):.2f}, "
             f"max {max(vals):,}")
    emit()
    emit("Most connected entities:")
    emit()
    emit("| Entity | Type | Degree |")
    emit("|--------|------|-------:|")
    top = sorted(total_deg.items(), key=lambda kv: kv[1], reverse=True)[:10]
    for nid, d in top:
        emit(f"| {nodes[nid]['label'] or nid} | "
             f"{nodes[nid]['type'] or '(blank)'} | {d:,} |")
    emit()

    # connected components -- union-find over an undirected view
    parent = {nid: nid for nid in nodes}

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
    comp_sizes = sorted(Counter(find(nid) for nid in nodes).values(),
                        reverse=True)
    singletons = sum(1 for x in comp_sizes if x == 1)
    emit("Connected components (edges treated as undirected):")
    emit()
    emit(f"- **Number of components:** {len(comp_sizes):,}")
    emit(f"- **Largest component:** {comp_sizes[0]:,} entities "
         f"({pct(comp_sizes[0], n_nodes)} of graph)")
    emit(f"- **Singleton components:** {singletons:,}")
    emit(f"- **Top-10 component sizes:** {comp_sizes[:10]}")

    # -- 9. Data-quality checks -------------------------------------------
    section("9. Data-quality checks")
    self_loops = [e for e in edges if e["s"] == e["o"]]
    triple_counter = Counter((e["s"], e["p"], e["o"]) for e in edges)
    dup_triples = {k: c for k, c in triple_counter.items() if c > 1}
    redundant = sum(c - 1 for c in dup_triples.values())
    missing_type = [nid for nid, n in nodes.items() if not n["type"]]
    dup_detail = (f" ({', '.join(sorted(set(dup_ids))[:10])})"
                  if dup_ids else "")
    emit(f"- **Duplicate node IDs:** {len(dup_ids)}{dup_detail}")
    emit(f"- **Self-loop edges (subject == object):** {len(self_loops)}")
    emit(f"- **Duplicate triples (same s,p,o more than once):** "
         f"{len(dup_triples)} -- {redundant:,} redundant edges")
    emit(f"- **Dangling edges (endpoint not in node table):** {len(dangling)}")
    emit(f"- **Entities with missing type:** {len(missing_type)}")
    emit(f"- **Orphan entities (degree 0):** {len(orphans)}")
    if orphans:
        emit()
        emit(f"  Orphan entity IDs (first 20): {', '.join(orphans[:20])}")

    # -- 10. Summary for the manuscript -----------------------------------
    section("10. Summary for the manuscript")
    emit("Headline numbers for the Results section:")
    emit()
    emit(f"- DietIBD-KG comprises **{n_nodes:,} entities** linked by "
         f"**{n_edges:,} typed, directed edges** "
         f"({n_triples:,} unique triples; multiplicity {mult:.2f}).")
    emit("- Entities: "
         + ", ".join(f"{c:,} {t or '(untyped)'}"
                     for t, c in type_counts.most_common())
         + ".")
    emit(f"- Provenance: {n_cur:,} curated edges ({pct(n_cur, n_edges)}) "
         f"and {n_lit:,} literature-derived edges ({pct(n_lit, n_edges)}).")
    emit(f"- Literature evidence draws on {len(pmids):,} distinct "
         f"PubMed articles.")
    emit(f"- Largest connected component covers "
         f"{pct(comp_sizes[0], n_nodes)} of all entities.")
    emit(f"- Schema validation: {len(core_violations)} core-predicate and "
         f"{len(curated_violations)} curated-predicate violations.")
    emit()

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print()
    print(f"=== Report written to {REPORT_PATH} ===")


if __name__ == "__main__":
    main()
