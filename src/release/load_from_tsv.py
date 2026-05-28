"""Rebuild the DietIBD-KG Neo4j graph from the consolidated v1.2.0 TSVs.

This makes Neo4j an exact mirror of the released TSV files (the master copy).
It DELETES the current graph and reloads nodes and edges from the TSVs,
reconstructing the schema the access package expects:

  - node label  = the entity `type` column (Food/Bioactive/Microbe/IBD_Outcome/Pathway)
  - node props  = id, label, source (= the `origin` column: "LLM" or "curated")
  - rel type    = the `predicate` column
  - rel props   = sources (list), evidence_strength (float), evidence_count (int),
                  evidence_types (list), evidence_pmid, evidence_type, evidence_span

Usage:
    python src/release/load_from_tsv.py \
        --nodes release/dietibdkg-v1.2.0/nodes.tsv \
        --edges release/dietibdkg-v1.2.0/edges.tsv
Add --yes to skip the confirmation prompt.
"""
import argparse
import csv
from collections import defaultdict

from neo4j import GraphDatabase

from dietibdkg import config

NODE_LABELS = {"Food", "Bioactive", "Microbe", "IBD_Outcome", "Pathway"}
PREDICATES = {
    "CONTAINS", "PRODUCES", "INCREASES_ABUNDANCE_OF", "DECREASES_ABUNDANCE_OF",
    "INCREASED_IN", "DECREASED_IN", "INCREASES_MARKER", "DECREASES_MARKER",
    "INVOLVES", "IS_LOW_FODMAP_FOOD", "MODULATES_CLUSTER", "HAS_HIGH_FODMAP_CONTENT_OF",
}


def split_list(s):
    return [x for x in s.split("|") if x] if s else []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", required=True)
    ap.add_argument("--edges", required=True)
    ap.add_argument("--yes", action="store_true", help="skip confirmation")
    args = ap.parse_args()

    with open(args.nodes, encoding="utf-8") as f:
        nodes = list(csv.DictReader(f, delimiter="\t"))
    with open(args.edges, encoding="utf-8") as f:
        edges = list(csv.DictReader(f, delimiter="\t"))

    # validate against the known schema before touching the DB
    bad_t = {r["type"] for r in nodes} - NODE_LABELS
    bad_p = {r["predicate"] for r in edges} - PREDICATES
    assert not bad_t, f"unexpected node types: {bad_t}"
    assert not bad_p, f"unexpected predicates: {bad_p}"
    id2type = {r["id"]: r["type"] for r in nodes}
    missing = {r["subject_id"] for r in edges} | {r["object_id"] for r in edges}
    missing -= set(id2type)
    assert not missing, f"{len(missing)} edge endpoints missing from nodes, e.g. {list(missing)[:5]}"

    print(f"Parsed {len(nodes):,} nodes and {len(edges):,} edges from TSVs.")
    if not args.yes:
        ans = input("This will DELETE the current Neo4j graph and reload it. Type 'yes': ")
        if ans.strip().lower() != "yes":
            print("aborted")
            return

    drv = GraphDatabase.driver(
        config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))
    with drv.session() as s:
        print("wiping current graph...")
        s.run("MATCH (n) DETACH DELETE n")

        # id uniqueness per label (also serves as the lookup index for edge loading)
        for lbl in NODE_LABELS:
            try:
                s.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{lbl}) REQUIRE n.id IS UNIQUE")
            except Exception as ex:                       # Neo4j 4.x has different syntax
                print(f"  (constraint on :{lbl} skipped: {ex}); creating plain index")
                s.run(f"CREATE INDEX IF NOT EXISTS FOR (n:{lbl}) ON (n.id)")

        # nodes, grouped by label so the label can be static in the query
        by_label = defaultdict(list)
        for r in nodes:
            by_label[r["type"]].append(
                {"id": r["id"], "label": r["label"], "source": r["origin"]})
        for lbl, rows in by_label.items():
            s.run(f"UNWIND $rows AS row "
                  f"CREATE (n:{lbl} {{id: row.id, label: row.label, source: row.source}})",
                  rows=rows)
            print(f"  loaded {len(rows):,} :{lbl} nodes")

        # edges, grouped by (predicate, subject_type, object_type) for indexed matching
        by_group = defaultdict(list)
        for r in edges:
            key = (r["predicate"], id2type[r["subject_id"]], id2type[r["object_id"]])
            by_group[key].append({
                "sid": r["subject_id"], "oid": r["object_id"],
                "sources": split_list(r["sources"]),
                "evidence_strength": float(r["evidence_strength"]) if r["evidence_strength"] else None,
                "evidence_count": int(r["evidence_count"]) if r["evidence_count"] else None,
                "evidence_types": split_list(r["evidence_types"]),
                "evidence_pmid": r["evidence_pmid"] or None,
                "evidence_type": r["evidence_type"] or None,
                "evidence_span": r["evidence_span"] or None,
            })
        total = 0
        for (pred, st, ot), rows in by_group.items():
            s.run(f"""
                UNWIND $rows AS row
                MATCH (s:{st} {{id: row.sid}}), (o:{ot} {{id: row.oid}})
                CREATE (s)-[r:{pred}]->(o)
                SET r.sources = row.sources,
                    r.evidence_strength = row.evidence_strength,
                    r.evidence_count = row.evidence_count,
                    r.evidence_types = row.evidence_types,
                    r.evidence_pmid = row.evidence_pmid,
                    r.evidence_type = row.evidence_type,
                    r.evidence_span = row.evidence_span
            """, rows=rows)
            total += len(rows)
        print(f"  loaded {total:,} edges across {len(by_group)} (predicate, subject, object) groups")

        nc = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        ec = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        es = s.run("MATCH ()-[r]->() RETURN count(r.evidence_strength) AS c").single()["c"]
        old = s.run("MATCH ()-[r]->() RETURN count(r.confidence) AS c").single()["c"]
        print(f"\nNeo4j now holds: {nc:,} nodes, {ec:,} edges, "
              f"{es:,} with evidence_strength, {old} with confidence")
        print("expected:        4,539 nodes, 16,146 edges, 16,146 with evidence_strength, 0 with confidence")
    drv.close()


if __name__ == "__main__":
    main()
