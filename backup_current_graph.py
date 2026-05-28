"""Snapshot the current (live) Neo4j graph to TSVs. Online, no sudo, no stop.

Writes backups/nodes_current.tsv and backups/edges_current.tsv in the same
format as the release TSVs, so the snapshot can be restored if needed with:

    python src/release/load_from_tsv.py \
        --nodes backups/nodes_current.tsv \
        --edges backups/edges_current.tsv
"""
import csv
import os

from neo4j import GraphDatabase

from dietibdkg import config

os.makedirs("backups", exist_ok=True)
drv = GraphDatabase.driver(
    config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))

with drv.session() as s:
    with open("backups/nodes_current.tsv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["id", "label", "type", "origin"])
        n = 0
        for r in s.run("MATCH (n) RETURN n.id AS id, n.label AS label, "
                       "labels(n)[0] AS type, n.source AS source "
                       "ORDER BY type, label"):
            origin = "LLM" if r["source"] == "LLM" else "curated"
            w.writerow([r["id"], r["label"], r["type"], origin])
            n += 1
    print(f"nodes snapshotted: {n:,}")

    with open("backups/edges_current.tsv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["subject_id", "subject_label", "predicate",
                    "object_id", "object_label", "sources", "evidence_strength",
                    "evidence_count", "evidence_types", "evidence_pmid",
                    "evidence_type", "evidence_span"])
        m = 0
        for r in s.run("""
            MATCH (s)-[r]->(o)
            RETURN s.id AS sid, s.label AS sl, type(r) AS pred,
                   o.id AS oid, o.label AS ol,
                   r.sources AS sources, r.evidence_strength AS es,
                   r.evidence_count AS ec, r.evidence_types AS ets,
                   r.evidence_pmid AS pmid, r.evidence_type AS et,
                   r.evidence_span AS espan
            ORDER BY pred, sl
        """):
            sources = "|".join(r["sources"]) if r["sources"] else ""
            ets = "|".join(r["ets"]) if r["ets"] else ""
            w.writerow([r["sid"], r["sl"], r["pred"], r["oid"], r["ol"],
                        sources, r["es"], r["ec"], ets,
                        r["pmid"] or "", r["et"] or "", r["espan"] or ""])
            m += 1
    print(f"edges snapshotted: {m:,}")

drv.close()
print("wrote backups/nodes_current.tsv and backups/edges_current.tsv")
