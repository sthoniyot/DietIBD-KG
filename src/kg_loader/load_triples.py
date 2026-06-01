"""Main DietIBD-KG loader.

Reads all 5 Phase B triple TSVs, applies canonical reconciliation,
deduplicates triples with confidence aggregation, then batch-loads
nodes and relationships into Neo4j.

Process:
  1. Load canonical_id_map.tsv (7 reconciliations)
  2. Read all 5 triples_*.tsv files
  3. Apply ID reconciliation (rewrites subject_id/object_id where applicable)
  4. Build node set: one entry per unique entity_id, with label and type
  5. Build edge set: one entry per (subject, predicate, object), aggregating
     confidence_max, confidence_min, evidence_count, sources across duplicates
  6. Batch-load nodes via MERGE
  7. Batch-load edges via MERGE
  8. Report statistics

Run with:
    python src/kg_loader/load_triples.py
"""
import csv
import sys
import time
from collections import defaultdict
from pathlib import Path

# Add src/ to path so we can import siblings (matches Phase B pattern)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kg_loader.neo4j_client import Neo4jClient

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED = PROJECT_ROOT / "data" / "processed"

TRIPLE_FILES = [
    PROCESSED / "triples_disbiome.tsv",
    PROCESSED / "triples_foodb_filtered.tsv",
    PROCESSED / "triples_bolte2021.tsv",
    PROCESSED / "triples_fodmap.tsv",
]

CANONICAL_MAP = PROCESSED / "canonical_id_map.tsv"

# Predicate -> relationship type (uppercase per Neo4j convention)
PREDICATE_TO_REL_TYPE = {
    "contains": "CONTAINS",
    "produces": "PRODUCES",
    "increases_abundance_of": "INCREASES_ABUNDANCE_OF",
    "decreases_abundance_of": "DECREASES_ABUNDANCE_OF",
    "modulates_cluster": "MODULATES_CLUSTER",
    "increased_in": "INCREASED_IN",
    "decreased_in": "DECREASED_IN",
    "increases_marker": "INCREASES_MARKER",
    "decreases_marker": "DECREASES_MARKER",
    "involves": "INVOLVES",
    "has_high_FODMAP_content_of": "HAS_HIGH_FODMAP_CONTENT_OF",
    "is_low_FODMAP_food": "IS_LOW_FODMAP_FOOD",
}


def step(msg):
    print(f"\n=== {msg} ===  [{time.strftime('%H:%M:%S')}]", flush=True)


# ---------------------------------------------------------------------------
# Stage 1: Load canonical reconciliation map
# ---------------------------------------------------------------------------

def load_canonical_map():
    """Return dict: source_id -> canonical_id."""
    mapping = {}
    with open(CANONICAL_MAP, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            mapping[row["source_id"].strip()] = row["canonical_id"].strip()
    return mapping


# ---------------------------------------------------------------------------
# Stage 2: Read all triples with reconciliation applied
# ---------------------------------------------------------------------------

def read_all_triples(canonical_map):
    """Yield triple dicts with reconciliation applied."""
    total = 0
    for filepath in TRIPLE_FILES:
        source_name = filepath.stem.replace("triples_", "")
        print(f"  Reading {filepath.name}...", end=" ", flush=True)
        count = 0
        with open(filepath, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                # Apply canonical reconciliation
                row["subject_id"] = canonical_map.get(
                    row["subject_id"], row["subject_id"]
                )
                row["object_id"] = canonical_map.get(
                    row["object_id"], row["object_id"]
                )
                # Tag with source file name
                row["_source_file"] = source_name
                yield row
                count += 1
        print(f"{count:,} rows")
        total += count
    print(f"  Total: {total:,} triple rows")


# ---------------------------------------------------------------------------
# Stage 3: Deduplicate into node-set and edge-set
# ---------------------------------------------------------------------------

def deduplicate(triples):
    """Build node-set (dict by id) and edge-set (dict by (s, p, o)).

    Edges aggregate properties across duplicate source assertions.
    """
    nodes = {}  # id -> node dict
    # edges keyed by (subject_id, predicate, object_id)
    edges_raw = defaultdict(list)

    for t in triples:
        # --- Subject node ---
        sid = t["subject_id"]
        if sid not in nodes:
            nodes[sid] = {
                "id": sid,
                "label": t["subject_label"],
                "type": t["subject_type"],
            }

        # --- Object node ---
        oid = t["object_id"]
        if oid not in nodes:
            nodes[oid] = {
                "id": oid,
                "label": t["object_label"],
                "type": t["object_type"],
            }

        # --- Edge ---
        predicate = t["predicate"]
        if predicate not in PREDICATE_TO_REL_TYPE:
            # Skip unrecognized predicates rather than fail
            continue

        edge_key = (sid, predicate, oid)
        edges_raw[edge_key].append(t)

    # Now aggregate edges: each unique (s, p, o) becomes one edge with
    # combined provenance and confidence stats.
    edges = []
    for (sid, predicate, oid), triple_list in edges_raw.items():
        confidences = [float(t["confidence"]) for t in triple_list if t.get("confidence")]
        sources = sorted(set(t["source"] for t in triple_list))
        evidence_types = sorted(set(t.get("evidence_type", "") for t in triple_list if t.get("evidence_type")))

        edge_props = {
            "predicate": predicate,
            "confidence": max(confidences) if confidences else 0.5,
            "confidence_min": min(confidences) if confidences else 0.5,
            "confidence_max": max(confidences) if confidences else 0.5,
            "evidence_count": len(triple_list),
            "sources": sources,
            "evidence_types": evidence_types,
        }

        edges.append({
            "subject_id": sid,
            "object_id": oid,
            "subject_type": triple_list[0]["subject_type"],
            "object_type": triple_list[0]["object_type"],
            "rel_type": PREDICATE_TO_REL_TYPE[predicate],
            "props": edge_props,
        })

    return nodes, edges


# ---------------------------------------------------------------------------
# Stage 4: Load nodes and edges into Neo4j
# ---------------------------------------------------------------------------

def load_nodes(client, nodes):
    """Group nodes by type and batch-load each group."""
    nodes_by_type = defaultdict(list)
    for nid, node in nodes.items():
        nodes_by_type[node["type"]].append(node)

    print(f"Nodes by type:")
    for ntype, lst in sorted(nodes_by_type.items()):
        print(f"  {ntype:<20} {len(lst):>6,}")

    print("\nLoading nodes into Neo4j...")
    for ntype, records in sorted(nodes_by_type.items()):
        print(f"  Loading {len(records):,} {ntype} nodes...", end=" ", flush=True)
        last = 0
        for done, total in client.batch_merge_nodes(ntype, records, batch_size=1000):
            last = done
        print(f"done ({last:,})")


def load_edges(client, edges):
    """Group edges by (rel_type, subject_type, object_type) and batch-load."""
    edges_by_grouping = defaultdict(list)
    for edge in edges:
        key = (edge["rel_type"], edge["subject_type"], edge["object_type"])
        edges_by_grouping[key].append({
            "subject_id": edge["subject_id"],
            "object_id": edge["object_id"],
            "props": edge["props"],
        })

    print(f"\nEdges by type:")
    for (rt, st, ot), lst in sorted(edges_by_grouping.items()):
        print(f"  ({st})-[:{rt}]->({ot})   {len(lst):>6,}")

    print("\nLoading edges into Neo4j...")
    for (rel_type, st, ot), records in sorted(edges_by_grouping.items()):
        print(f"  Loading {len(records):,} ({st})-[:{rel_type}]->({ot})...", end=" ", flush=True)
        last = 0
        for done, total in client.batch_merge_relationships(
            rel_type, st, ot, records, batch_size=1000
        ):
            last = done
        print(f"done ({last:,})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    overall_start = time.time()

    step("Stage 1: Load canonical reconciliation map")
    canonical_map = load_canonical_map()
    print(f"  {len(canonical_map)} reconciliations loaded")
    for sid, cid in canonical_map.items():
        print(f"    {sid:<25} -> {cid}")

    step("Stage 2: Read all triple TSVs (with reconciliation applied)")
    triples = list(read_all_triples(canonical_map))

    step("Stage 3: Deduplicate into nodes and edges")
    nodes, edges = deduplicate(triples)
    print(f"  Unique nodes: {len(nodes):,}")
    print(f"  Unique edges: {len(edges):,}  (from {len(triples):,} triple rows)")
    print(f"  Compression ratio: {len(edges) / len(triples) * 100:.1f}%")

    # Print evidence_count histogram
    from collections import Counter
    ev_counts = Counter(e["props"]["evidence_count"] for e in edges)
    print(f"\n  Edges by evidence_count (# sources asserting):")
    for count, n in sorted(ev_counts.items()):
        print(f"    {count} source(s): {n:>5,} edges")

    step("Stage 4: Load into Neo4j")
    client = Neo4jClient()
    try:
        load_nodes(client, nodes)
        load_edges(client, edges)

        # Verify counts
        step("Stage 5: Verify load")
        result = client.run("MATCH (n) RETURN count(n) AS n")
        n_loaded = result[0]["n"]
        result = client.run("MATCH ()-[r]->() RETURN count(r) AS r")
        r_loaded = result[0]["r"]
        print(f"  Neo4j now has {n_loaded:,} nodes, {r_loaded:,} relationships")
        print(f"  Expected:      {len(nodes):,} nodes, {len(edges):,} relationships")

        if n_loaded == len(nodes) and r_loaded == len(edges):
            print("  Counts match exactly.")
        else:
            print("  WARN: counts differ - investigate")
    finally:
        client.close()

    print(f"\nTotal runtime: {time.time() - overall_start:.1f}s")


if __name__ == "__main__":
    main()
