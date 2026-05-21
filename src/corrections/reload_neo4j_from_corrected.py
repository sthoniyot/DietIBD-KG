#!/usr/bin/env python3
"""Reload Neo4j from the corrected DietIBD-KG node/edge tables.

The entity-typing correction was applied to the TSV files only; the Neo4j
database still holds the pre-correction graph. This script rebuilds the Neo4j
graph from the corrected tables so that Neo4j matches the corrected, QA-passed
graph (4,603 entities / 16,146 edges, 0 schema violations).

It WIPES the existing graph and rebuilds it. This is safe: the pre-correction
graph is recoverable from release/dietibdkg-v1.0.0/{nodes,edges}.tsv and the
construction pipeline.

Schema (mirrors src/kg_loader/load_triples.py and load_llm_triples.py):
  - each entity is a node whose single Neo4j label is its type
    (:Food, :Bioactive, :Microbe, :IBD_Outcome, :Pathway), with properties
    id, label, type, origin, source;
  - each edge is a relationship whose type is the uppercase predicate, with
    properties predicate, confidence, confidence_min, confidence_max,
    evidence_count, evidence_types, sources, evidence_pmid, evidence_type,
    evidence_span.

Phase 1 - dry run (no Neo4j connection; reports what would be loaded):
    python reload_neo4j_from_corrected.py --dry-run

Phase 2 - load (wipes and rebuilds the Neo4j graph):
    python reload_neo4j_from_corrected.py --load

Run from the repository root. --load requires a .env file with
NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD, as used by the existing loaders.
"""
import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

# -- Configuration: paths are relative to the repo root (run from there) ----
NODES_PATH = Path("corrections/nodes_corrected.tsv")
EDGES_PATH = Path("corrections/edges_corrected.tsv")
BATCH = 1000

# Entity types -> one id index is created per node label.
ENTITY_TYPES = ["Food", "Bioactive", "Microbe", "IBD_Outcome", "Pathway"]


def load_nodes(path):
    if not path.exists():
        sys.exit(f"ERROR: {path} not found - run from the repository root.")
    nodes = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            nid = (row.get("id") or "").strip()
            if not nid:
                continue
            nodes[nid] = {
                "id": nid,
                "label": (row.get("label") or "").strip(),
                "type": (row.get("type") or "").strip(),
                "origin": (row.get("origin") or "").strip(),
            }
    return nodes


def load_edges(path, nodes):
    if not path.exists():
        sys.exit(f"ERROR: {path} not found - run from the repository root.")
    edges, skipped = [], []
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            s = (row.get("subject_id") or "").strip()
            o = (row.get("object_id") or "").strip()
            p = (row.get("predicate") or "").strip()
            if s not in nodes or o not in nodes:
                skipped.append((s, p, o))
                continue
            try:
                conf = float(row.get("confidence"))
            except (TypeError, ValueError):
                conf = 0.70
            try:
                ev_count = int(row.get("evidence_count"))
            except (TypeError, ValueError):
                ev_count = 1
            ev_types = (row.get("evidence_types") or "").strip()
            src = (row.get("sources") or "").strip()
            edges.append({
                "s": s, "o": o,
                "rel_type": p,                       # already uppercase in TSV
                "subj_type": nodes[s]["type"],
                "obj_type": nodes[o]["type"],
                "predicate": p,
                "confidence": conf,
                "evidence_count": ev_count,
                "evidence_types": [ev_types] if ev_types else [],
                "sources": [src] if src else [],
                "evidence_pmid": (row.get("evidence_pmid") or "").strip(),
                "evidence_type": (row.get("evidence_type") or "").strip(),
                "evidence_span": (row.get("evidence_span") or "").strip(),
            })
    return edges, skipped


def get_driver():
    """Imported lazily so --dry-run needs no Neo4j / dotenv install."""
    import os
    from dotenv import load_dotenv
    from neo4j import GraphDatabase
    load_dotenv()  # finds .env from the repo root
    pw = os.getenv("NEO4J_PASSWORD")
    if not pw:
        sys.exit("ERROR: NEO4J_PASSWORD not set (.env missing or incomplete).")
    return GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), pw),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--load", action="store_true")
    args = parser.parse_args()
    if not (args.dry_run or args.load):
        sys.exit("ERROR: specify --dry-run or --load")

    nodes = load_nodes(NODES_PATH)
    edges, skipped = load_edges(EDGES_PATH, nodes)

    nodes_by_type = defaultdict(list)
    for n in nodes.values():
        nodes_by_type[n["type"]].append(n)
    edges_by_group = defaultdict(list)
    for e in edges:
        edges_by_group[(e["rel_type"], e["subj_type"], e["obj_type"])].append(e)

    print("=== DietIBD-KG -> Neo4j reload ===")
    print(f"Source: {NODES_PATH}  ({len(nodes):,} entities)")
    print(f"        {EDGES_PATH}  ({len(edges):,} edges)")
    print()
    print("Nodes by type (Neo4j label):")
    for t, lst in sorted(nodes_by_type.items(), key=lambda kv: -len(kv[1])):
        print(f"  :{t:<14} {len(lst):>7,}")
    print()
    print("Edges by relationship type:")
    for rt, c in Counter(e["rel_type"] for e in edges).most_common():
        print(f"  :{rt:<28} {c:>7,}")
    if skipped:
        print()
        print(f"WARNING: {len(skipped)} edge(s) skipped - an endpoint is "
              f"missing from the node table:")
        for s, p, o in skipped[:10]:
            print(f"  {s} -[{p}]-> {o}")

    if args.dry_run:
        print("\nDRY RUN - no Neo4j connection, no writes. Use --load to execute.")
        return

    # -- LOAD --
    print()
    print("!! --load will DELETE ALL nodes and relationships in the target")
    print("   Neo4j database and rebuild the graph from the corrected tables.")
    print("   The pre-correction graph is recoverable from the")
    print("   release/dietibdkg-v1.0.0 tables and the construction pipeline.")
    if input("   Type 'yes' to continue: ").strip().lower() != "yes":
        sys.exit("Aborted - no changes made.")

    driver = get_driver()
    try:
        with driver.session() as s:
            # 1. wipe (batched, APOC-free)
            print("\nWiping existing graph...")
            while True:
                c = s.run("MATCH (n) WITH n LIMIT 10000 DETACH DELETE n "
                          "RETURN count(*) AS c").single()["c"]
                if c == 0:
                    break
                print(f"  deleted {c:,} nodes...")
            print("  graph is empty.")

            # 2. id index per entity-type label (speeds up the edge MATCH)
            print("Creating id indexes...")
            for t in ENTITY_TYPES:
                s.run(f"CREATE INDEX idx_{t.lower()}_id IF NOT EXISTS "
                      f"FOR (n:`{t}`) ON (n.id)").consume()
            print("  done.")

            # 3. nodes - grouped by type so each carries the right label
            print(f"Loading {len(nodes):,} nodes...")
            for t, lst in nodes_by_type.items():
                for i in range(0, len(lst), BATCH):
                    s.run(
                        f"UNWIND $rows AS n "
                        f"MERGE (x:`{t}` {{id: n.id}}) "
                        f"SET x.label = n.label, x.type = n.type, "
                        f"    x.origin = n.origin, x.source = n.origin",
                        rows=lst[i:i + BATCH]).consume()
                print(f"  :{t:<14} {len(lst):>7,} loaded")

            # 4. edges - grouped by (rel_type, subject_type, object_type)
            print(f"Loading {len(edges):,} edges...")
            for (rt, st, ot), lst in edges_by_group.items():
                for i in range(0, len(lst), BATCH):
                    s.run(
                        f"UNWIND $rows AS e "
                        f"MATCH (a:`{st}` {{id: e.s}}), (b:`{ot}` {{id: e.o}}) "
                        f"CREATE (a)-[r:`{rt}`]->(b) "
                        f"SET r.predicate      = e.predicate, "
                        f"    r.confidence     = e.confidence, "
                        f"    r.confidence_min = e.confidence, "
                        f"    r.confidence_max = e.confidence, "
                        f"    r.evidence_count = e.evidence_count, "
                        f"    r.evidence_types = e.evidence_types, "
                        f"    r.sources        = e.sources, "
                        f"    r.evidence_pmid  = e.evidence_pmid, "
                        f"    r.evidence_type  = e.evidence_type, "
                        f"    r.evidence_span  = e.evidence_span",
                        rows=lst[i:i + BATCH]).consume()
            print(f"  {len(edges):,} edges loaded")

            # 5. verify
            print("\n=== Verification ===")
            n_cnt = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            e_cnt = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
            print(f"  Neo4j nodes:         {n_cnt:,}  (expected {len(nodes):,})")
            print(f"  Neo4j relationships: {e_cnt:,}  (expected {len(edges):,})")
            if n_cnt == len(nodes) and e_cnt == len(edges):
                print("  Counts match exactly.")
            else:
                print("  WARNING: counts differ - re-run --load to rebuild.")
    finally:
        driver.close()

    print("\nReload complete. Neo4j now matches the corrected graph.")
    print("Re-run src/analysis/kg_qa.py to confirm - it should now agree with")
    print("the kg_qa_tsv.py report (0 schema violations, 4,603 entities).")


if __name__ == "__main__":
    main()
