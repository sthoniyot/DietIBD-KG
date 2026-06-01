"""Reload DietIBD-KG Neo4j with the v1.4.0 (KEGG-free) release.

This WIPES the current graph and reloads it from the *authoritative* consolidated
release files, so the live instance matches the paper / figures / GitHub release
(3,950 entities, 14,232 unique relationships).

IMPORTANT: load from the consolidated v1.4.0 TSVs below, NOT by re-running the
ingestion pipeline -- the pipeline currently yields ~4,610 nodes, which is the
discrepancy you are trying to eliminate.

Schema mirrors src/kg_loader/load_triples.py:
  * node label  = entity type  (:Food / :Microbe / :Bioactive / :IBD_Outcome)
  * node props  = id (unique), label, type, origin
  * rel type    = predicate (already uppercase in the consolidated file)
  * rel props   = predicate, confidence (= max evidence_strength), confidence_min,
                  confidence_max, evidence_count (# source rows merged), sources[],
                  evidence_types[]   -- these match load_triples.py exactly, so
                  existing queries keep working -- PLUS two additive literature
                  properties: evidence_pmids[], evidence_spans[]
    (The consolidated file's column is named "evidence_strength"; it is stored
     here as "confidence" to match the original graph. To rename it instead,
     change the three "confidence*" keys below.)

One relationship is created per unique (subject, predicate, object); duplicate
source assertions are aggregated. Sum of evidence_count == 15,628 (the paper's
edge total).

Run (from repo root, with your conda env active):
    NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=*** \
        python reload_neo4j_v1_4_0.py

Requires:  pip install neo4j
"""
import csv
import os
import sys
from collections import defaultdict

from neo4j import GraphDatabase

# ---------------------------------------------------------------------------
# Configuration  (edit these two paths to your repo's data/processed copies)
# ---------------------------------------------------------------------------
NODES_TSV = os.environ.get("NODES_TSV", "nodes_consolidated_v1.4.0.tsv")
EDGES_TSV = os.environ.get("EDGES_TSV", "edges_consolidated_v1.4.0.tsv")

URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
USER = os.environ.get("NEO4J_USER", "neo4j")
PASSWORD = os.environ.get("NEO4J_PASSWORD", "neo4j")
DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")

BATCH = 1000

# Controlled vocabularies (used to validate before embedding in Cypher)
VALID_LABELS = {"Food", "Microbe", "Bioactive", "IBD_Outcome"}
VALID_RELS = {
    "CONTAINS", "PRODUCES", "INCREASES_ABUNDANCE_OF", "DECREASES_ABUNDANCE_OF",
    "MODULATES_CLUSTER", "INCREASED_IN", "DECREASED_IN", "INCREASES_MARKER",
    "DECREASES_MARKER", "HAS_HIGH_FODMAP_CONTENT_OF", "IS_LOW_FODMAP_FOOD",
}


# ---------------------------------------------------------------------------
# Read + aggregate the release files
# ---------------------------------------------------------------------------
def read_nodes(path):
    """id -> {id,label,type,origin}; also id -> type map for edge grouping."""
    nodes_by_label = defaultdict(list)
    id2type = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            t = r["type"].strip()
            if t not in VALID_LABELS:
                sys.exit(f"Unexpected node type {t!r} in {path}")
            id2type[r["id"]] = t
            nodes_by_label[t].append({
                "id": r["id"],
                "label": r["label"],
                "type": t,
                "origin": r.get("origin", ""),
            })
    return nodes_by_label, id2type


def read_edges(path, id2type):
    """Aggregate to one record per (s, predicate, o), grouped for loading."""
    agg = {}  # (s,p,o) -> aggregation dict
    missing = 0
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            s, p, o = r["subject_id"], r["predicate"].strip(), r["object_id"]
            if p not in VALID_RELS:
                continue
            if s not in id2type or o not in id2type:
                missing += 1
                continue
            key = (s, p, o)
            a = agg.get(key)
            if a is None:
                a = agg[key] = {
                    "n": 0, "strengths": [], "sources": set(),
                    "etypes": set(), "pmids": set(), "spans": set(),
                }
            a["n"] += 1
            if r.get("evidence_strength"):
                try:
                    a["strengths"].append(float(r["evidence_strength"]))
                except ValueError:
                    pass
            if r.get("sources"):
                a["sources"].add(r["sources"].strip())
            if r.get("evidence_types"):
                a["etypes"].add(r["evidence_types"].strip())
            if r.get("evidence_pmid"):
                a["pmids"].add(r["evidence_pmid"].strip())
            if r.get("evidence_span"):
                a["spans"].add(r["evidence_span"].strip())

    if missing:
        print(f"  WARNING: {missing} edge rows skipped (endpoint id not in nodes file)")

    # group by (rel_type, subject_type, object_type) -> list of param rows
    grouped = defaultdict(list)
    for (s, p, o), a in agg.items():
        strengths = a["strengths"] or [0.5]
        props = {
            "predicate": p,
            "confidence": max(strengths),
            "confidence_min": min(strengths),
            "confidence_max": max(strengths),
            "evidence_count": a["n"],
            "sources": sorted(a["sources"]),
            "evidence_types": sorted(a["etypes"]),
            "evidence_pmids": sorted(a["pmids"]),
            "evidence_spans": sorted(a["spans"]),
        }
        grouped[(p, id2type[s], id2type[o])].append({"s": s, "o": o, "props": props})
    return grouped, len(agg)


# ---------------------------------------------------------------------------
# Load into Neo4j
# ---------------------------------------------------------------------------
def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def main():
    nodes_by_label, id2type = read_nodes(NODES_TSV)
    n_nodes = sum(len(v) for v in nodes_by_label.values())
    grouped_edges, n_unique = read_edges(EDGES_TSV, id2type)
    n_rows = sum(len(v) for v in grouped_edges.values())

    print(f"Parsed {n_nodes:,} nodes, {n_unique:,} unique relationships "
          f"(from {EDGES_TSV}).")
    print("Nodes by type:")
    for lbl, recs in sorted(nodes_by_label.items()):
        print(f"  {lbl:<14}{len(recs):>6,}")

    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    try:
        with driver.session(database=DATABASE) as s:
            print("\nWiping existing graph...")
            # Small graph (<~20k elements); plain delete is fine. For a very
            # large graph, instead run in cypher-shell:
            #   MATCH (n) CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS
            s.run("MATCH (n) DETACH DELETE n").consume()

            print("Creating uniqueness constraints...")
            for lbl in sorted(nodes_by_label):
                s.run(
                    f"CREATE CONSTRAINT {lbl.lower()}_id IF NOT EXISTS "
                    f"FOR (n:`{lbl}`) REQUIRE n.id IS UNIQUE"
                ).consume()

            print("Loading nodes...")
            for lbl, recs in sorted(nodes_by_label.items()):
                q = (f"UNWIND $rows AS row MERGE (n:`{lbl}` {{id: row.id}}) "
                     f"SET n.label = row.label, n.type = row.type, n.origin = row.origin")
                for batch in chunks(recs, BATCH):
                    s.run(q, rows=batch).consume()
                print(f"  {lbl:<14}{len(recs):>6,} loaded")

            print("Loading relationships (one per unique triple, provenance aggregated)...")
            for (rel, st, ot), recs in sorted(grouped_edges.items()):
                q = (f"UNWIND $rows AS row "
                     f"MATCH (a:`{st}` {{id: row.s}}) MATCH (b:`{ot}` {{id: row.o}}) "
                     f"MERGE (a)-[r:`{rel}`]->(b) SET r += row.props")
                for batch in chunks(recs, BATCH):
                    s.run(q, rows=batch).consume()
                print(f"  ({st})-[:{rel}]->({ot}){'':<2}{len(recs):>6,}")

            # Verify
            nb = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            rb = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
            ev = s.run("MATCH ()-[r]->() RETURN sum(r.evidence_count) AS c").single()["c"]
            print(f"\nNeo4j now has {nb:,} nodes, {rb:,} relationships "
                  f"(sum of evidence_count = {ev:,}).")
            ok = (nb == n_nodes and rb == n_unique)
            print("Counts match the release." if ok else "WARN: counts differ - investigate.")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
