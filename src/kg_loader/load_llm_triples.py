"""Stage 6: Load LLM-extracted triples into Neo4j (plain Cypher, no APOC).

Reads production batch output, normalizes entity names, matches against
existing Neo4j nodes by `label`, creates new nodes for unmatched entities,
filters out schema-violating triples, and creates new LLM-tagged edges.

Phase 1: dry-run
    python src/kg_loader/load_llm_triples.py --dry-run \\
        --input data/processed/llm_extractions/extractions_production_*.tsv

Phase 2: load
    python src/kg_loader/load_llm_triples.py --load \\
        --input data/processed/llm_extractions/extractions_production_*.tsv
"""
import argparse
import csv
import glob
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

# Schema (must match Phase C design)
PREDICATE_TYPES = {
    "contains": ("Food", "Bioactive"),
    "produces": ("Microbe", "Bioactive"),
    "increases_abundance_of": ("Food", "Microbe"),
    "decreases_abundance_of": ("Food", "Microbe"),
    "increased_in": ("Microbe", "IBD_Outcome"),
    "decreased_in": ("Microbe", "IBD_Outcome"),
    "increases_marker": ("Food", "IBD_Outcome"),
    "decreases_marker": ("Food", "IBD_Outcome"),
    "has_high_FODMAP_content_of": ("Food", "Bioactive"),
}

GREEK = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta",
    "ε": "epsilon", "ζ": "zeta", "η": "eta", "θ": "theta",
    "ι": "iota", "κ": "kappa", "λ": "lambda", "μ": "mu",
    "ν": "nu", "ξ": "xi", "ο": "omicron", "π": "pi",
    "ρ": "rho", "σ": "sigma", "τ": "tau", "υ": "upsilon",
    "φ": "phi", "χ": "chi", "ψ": "psi", "ω": "omega",
    "Α": "alpha", "Β": "beta", "Γ": "gamma", "Δ": "delta",
    "Ε": "epsilon", "Π": "pi", "Σ": "sigma",
}
LEADING_STOPS = {"the", "a", "an"}
DISEASE_CANON = {
    "uc": "ulcerative colitis", "cd": "crohn s disease",
    "ibd": "inflammatory bowel disease", "ibs": "irritable bowel syndrome",
    "crohn disease": "crohn s disease", "crohns disease": "crohn s disease",
}


def normalize_name(name):
    if not name or name == "-":
        return ""
    s = name.lower().strip()
    for g, l in GREEK.items():
        s = s.replace(g, l)
    s = s.replace("_", " ")
    s = re.sub(r"[^\w\s-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    tokens = s.split()
    while tokens and tokens[0] in LEADING_STOPS:
        tokens.pop(0)
    s = " ".join(tokens)
    if s in DISEASE_CANON:
        s = DISEASE_CANON[s]
    return s


def name_synonyms(name):
    base = normalize_name(name)
    if not base:
        return set()
    variants = {base}
    if base.endswith("s") and len(base) > 3:
        variants.add(base[:-1])
    else:
        variants.add(base + "s")
    return variants


def get_driver():
    return GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD")),
    )


def load_existing_nodes(driver):
    nodes_by_label = {}
    with driver.session() as session:
        for r in session.run("""
            MATCH (n) WHERE n.label IS NOT NULL
            RETURN n.id AS id, n.label AS label, labels(n)[0] AS type
        """):
            for variant in name_synonyms(r["label"]):
                if variant not in nodes_by_label:
                    nodes_by_label[variant] = (r["id"], r["label"], r["type"])
    return nodes_by_label


def load_triples_from_tsv(tsv_path):
    triples = []
    with open(tsv_path, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if r["predicate"] in ("NONE", "ERROR", ""):
                continue
            triples.append(r)
    return triples


def resolve_entity(name, llm_type, existing, new_nodes):
    """Match name against existing nodes; create new if no match."""
    norm = normalize_name(name)
    match = existing.get(norm)
    if match is None:
        for v in name_synonyms(name):
            if v in existing:
                match = existing[v]
                break

    if match:
        return match[0], match[1], match[2], False  # id, label, type, is_new

    # New node
    syn_id = f"LLM:{norm.replace(' ', '_')[:80]}"
    if syn_id not in new_nodes:
        new_nodes[syn_id] = {"label": name, "type": llm_type}
    return syn_id, name, llm_type, True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--load", action="store_true")
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()

    if not (args.dry_run or args.load):
        sys.exit("ERROR: specify --dry-run or --load")

    input_files = sorted(glob.glob(args.input)) if "*" in args.input else [args.input]
    if not input_files:
        sys.exit(f"ERROR: no files matched {args.input}")
    tsv_path = input_files[-1]

    driver = get_driver()
    print(f"Loading existing Neo4j nodes...")
    existing = load_existing_nodes(driver)
    print(f"  {len(existing):,} normalized-name -> node mappings indexed")

    print(f"\nLoading triples from {tsv_path}...")
    triples = load_triples_from_tsv(tsv_path)
    print(f"  {len(triples):,} real triples")

    # Resolution pass
    print(f"\nResolving entities and validating schema...")
    new_nodes = {}
    resolved_triples = []
    schema_dropped = 0
    matched_count = 0
    new_count = 0

    for t in triples:
        sub_id, _, sub_type, sub_is_new = resolve_entity(
            t["subject_name"], t["subject_type"], existing, new_nodes)
        obj_id, _, obj_type, obj_is_new = resolve_entity(
            t["object_name"], t["object_type"], existing, new_nodes)

        matched_count += (not sub_is_new) + (not obj_is_new)
        new_count += sub_is_new + obj_is_new

        # Schema validation: predicate must match the *resolved* types
        expected = PREDICATE_TYPES.get(t["predicate"])
        if not expected or (sub_type, obj_type) != expected:
            schema_dropped += 1
            continue

        try:
            conf = float(t["confidence"])
        except (ValueError, TypeError):
            conf = 0.70

        resolved_triples.append({
            "sub_id": sub_id, "obj_id": obj_id,
            "predicate": t["predicate"], "rel_type": t["predicate"].upper(),
            "evidence_pmid": t["pmid"],
            "evidence_span": t["evidence_span"][:1000],
            "evidence_type": t["evidence_type"],
            "confidence": conf,
        })

    # Filter new_nodes to only those actually referenced by surviving edges
    used_ids = set()
    for t in resolved_triples:
        used_ids.add(t["sub_id"])
        used_ids.add(t["obj_id"])
    new_nodes = {k: v for k, v in new_nodes.items() if k in used_ids}

    print(f"\n=== Resolution Report ===")
    total = len(triples) * 2
    print(f"  Entity lookups:           {total:,}")
    print(f"  Matched to existing:      {matched_count:,} ({matched_count/total*100:.1f}%)")
    print(f"  New entities referenced:  {len(new_nodes):,}")
    print(f"  Triples dropped (schema): {schema_dropped:,}")
    print(f"  Triples surviving:        {len(resolved_triples):,}")

    print(f"\nNew nodes by type:")
    nt = Counter(d["type"] for d in new_nodes.values())
    for k, v in nt.most_common():
        print(f"  {k:<20} {v:>5,}")

    print(f"\nEdges by relationship type:")
    rt = Counter(t["rel_type"] for t in resolved_triples)
    for k, v in rt.most_common():
        print(f"  {k:<35} {v:>5,}")

    if args.dry_run:
        print(f"\nDRY RUN - no writes. Use --load to execute.")
        driver.close()
        return

    # ─── LOAD ───
    print(f"\n=== Loading to Neo4j ===")
    BATCH = args.batch_size

    # Group new nodes by type
    nodes_by_type = defaultdict(list)
    for nid, d in new_nodes.items():
        nodes_by_type[d["type"]].append({"id": nid, "label": d["label"]})

    print(f"Creating {len(new_nodes):,} new nodes (grouped by type)...")
    with driver.session() as session:
        for node_type, nodes in nodes_by_type.items():
            print(f"  {node_type}: {len(nodes):,} nodes...", end=" ", flush=True)
            for i in range(0, len(nodes), BATCH):
                chunk = nodes[i:i+BATCH]
                # MERGE makes it idempotent: re-running won't duplicate
                cypher = f"""
                    UNWIND $nodes AS n
                    MERGE (x:`{node_type}` {{id: n.id}})
                    ON CREATE SET x.label = n.label, x.type = $type, x.source = 'LLM'
                """
                session.run(cypher, nodes=chunk, type=node_type).consume()
            print("done")

    # Group edges by relationship type
    edges_by_type = defaultdict(list)
    for t in resolved_triples:
        edges_by_type[t["rel_type"]].append(t)

    print(f"\nCreating {len(resolved_triples):,} edges (grouped by type)...")
    with driver.session() as session:
        for rel_type, edges in edges_by_type.items():
            print(f"  {rel_type}: {len(edges):,} edges...", end=" ", flush=True)
            for i in range(0, len(edges), BATCH):
                chunk = edges[i:i+BATCH]
                cypher = f"""
                    UNWIND $edges AS e
                    MATCH (s {{id: e.sub_id}}), (o {{id: e.obj_id}})
                    CREATE (s)-[r:`{rel_type}`]->(o)
                    SET r.predicate      = e.predicate,
                        r.confidence     = e.confidence,
                        r.confidence_min = e.confidence,
                        r.confidence_max = e.confidence,
                        r.evidence_count = 1,
                        r.evidence_types = [e.evidence_type],
                        r.sources        = ['LLM'],
                        r.evidence_pmid  = e.evidence_pmid,
                        r.evidence_span  = e.evidence_span,
                        r.evidence_type  = e.evidence_type
                """
                session.run(cypher, edges=chunk).consume()
            print("done")

    print(f"\n=== Post-load Neo4j state ===")
    with driver.session() as session:
        n = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        e = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        e_llm = session.run("""
            MATCH ()-[r]->() WHERE 'LLM' IN r.sources RETURN count(r) AS c
        """).single()["c"]
        print(f"  Total nodes:    {n:,}")
        print(f"  Total edges:    {e:,}")
        print(f"  LLM edges:      {e_llm:,}")
        print(f"  Curated edges:  {e - e_llm:,}")

    driver.close()
    print(f"\nStage 6 load complete.")


if __name__ == "__main__":
    main()
