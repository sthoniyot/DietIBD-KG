"""Export the DietIBD-KG from Neo4j to triple format for embedding training.

Outputs:
  - data/processed/embeddings/kg_triples.tsv : unique (head, rel, tail), no header
  - data/processed/embeddings/kg_nodes.tsv   : id, label, type metadata

Usage:
    python src/analysis/export_triples.py
"""
import csv
import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

OUT_DIR = PROJECT_ROOT / "data" / "processed" / "embeddings"
TRIPLES_FILE = OUT_DIR / "kg_triples.tsv"
NODES_FILE = OUT_DIR / "kg_nodes.tsv"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD")),
    )

    with driver.session() as s:
        print("Exporting triples...")
        triples = set()
        for r in s.run("""
            MATCH (a)-[r]->(b)
            RETURN a.id AS h, type(r) AS rel, b.id AS t
        """):
            triples.add((r["h"], r["rel"], r["t"]))

        print("Exporting node metadata...")
        nodes = []
        for r in s.run("""
            MATCH (n) RETURN n.id AS id, n.label AS label, labels(n)[0] AS type
        """):
            nodes.append((r["id"], r["label"], r["type"]))

    driver.close()

    # Write triples (no header — PyKEEN TriplesFactory default format)
    with open(TRIPLES_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        for h, rel, t in sorted(triples):
            w.writerow([h, rel, t])

    # Write node metadata (with header)
    with open(NODES_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["id", "label", "type"])
        for nid, label, ntype in sorted(nodes):
            w.writerow([nid, label, ntype])

    # Summary
    rels = sorted(set(r for _, r, _ in triples))
    print(f"\n=== Export Complete ===")
    print(f"  Unique triples:  {len(triples):,}")
    print(f"  Entities:        {len(nodes):,}")
    print(f"  Relation types:  {len(rels)}")
    print(f"  Triples file:    {TRIPLES_FILE}")
    print(f"  Nodes file:      {NODES_FILE}")


if __name__ == "__main__":
    main()
