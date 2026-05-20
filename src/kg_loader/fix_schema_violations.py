"""Objective 1 QA fix: resolve schema violations identified by kg_qa.py.

Three-part fix:
  1. Schema expansion: the modulation predicates (*_ABUNDANCE_OF, *_MARKER)
     originally restricted subjects to Food. Biologically, bioactives and
     microbes also modulate abundance and markers. Schema is refined to
     permit subject in {Food, Bioactive, Microbe} for these predicates.
  2. Node relabelling: nodes whose label disagrees with the type implied
     by their edges (majority vote over type-fixing edge roles) are
     relabelled. Fixes LLM type-classification inconsistency.
  3. Edge dropping: edges still violating the (expanded) schema after
     relabelling are genuinely mis-predicated and are deleted. Self-loops
     are always dropped.

Usage:
    python src/kg_loader/fix_schema_violations.py --dry-run
    python src/kg_loader/fix_schema_violations.py --apply
"""
import argparse
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

# Expanded schema: predicate -> (allowed subject types, allowed object types)
SCHEMA = {
    "CONTAINS":                   ({"Food"},                       {"Bioactive"}),
    "PRODUCES":                   ({"Microbe"},                    {"Bioactive"}),
    "INCREASES_ABUNDANCE_OF":     ({"Food", "Bioactive", "Microbe"}, {"Microbe"}),
    "DECREASES_ABUNDANCE_OF":     ({"Food", "Bioactive", "Microbe"}, {"Microbe"}),
    "INCREASED_IN":               ({"Microbe"},                    {"IBD_Outcome"}),
    "DECREASED_IN":               ({"Microbe"},                    {"IBD_Outcome"}),
    "INCREASES_MARKER":           ({"Food", "Bioactive", "Microbe"}, {"IBD_Outcome"}),
    "DECREASES_MARKER":           ({"Food", "Bioactive", "Microbe"}, {"IBD_Outcome"}),
    "HAS_HIGH_FODMAP_CONTENT_OF": ({"Food"},                       {"Bioactive"}),
    # curated-only predicates — used for vote inference, not modified
    "INVOLVES":                   ({"Pathway"},                    {"Bioactive"}),
    "IS_LOW_FODMAP_FOOD":         ({"Food"},                       {"Bioactive"}),
    "MODULATES_CLUSTER":          ({"Food"},                       {"Microbe"}),
}


def get_driver():
    return GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD")),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not (args.dry_run or args.apply):
        sys.exit("ERROR: specify --dry-run or --apply")

    driver = get_driver()

    # ── Load nodes and edges ──
    print("Loading nodes and edges from Neo4j...")
    with driver.session() as s:
        nodes = {}  # id -> current label
        for r in s.run("MATCH (n) RETURN n.id AS id, labels(n)[0] AS lbl"):
            nodes[r["id"]] = r["lbl"]
        edges = []  # (subj_id, rel_type, obj_id, element_id)
        for r in s.run("""
            MATCH (a)-[r]->(b)
            RETURN a.id AS s, type(r) AS rt, b.id AS o, elementId(r) AS eid
        """):
            edges.append((r["s"], r["rt"], r["o"], r["eid"]))
    print(f"  {len(nodes):,} nodes, {len(edges):,} edges")

    # ── Step 1: vote on each node's correct type ──
    # A node gets a vote from an edge role only when that role's allowed
    # type set is unambiguous (exactly one type).
    print("\nInferring correct node types by edge-role voting...")
    votes = defaultdict(Counter)
    for sub, rt, obj, _ in edges:
        if rt not in SCHEMA:
            continue
        allowed_sub, allowed_obj = SCHEMA[rt]
        if len(allowed_sub) == 1 and sub in nodes:
            votes[sub][next(iter(allowed_sub))] += 1
        if len(allowed_obj) == 1 and obj in nodes:
            votes[obj][next(iter(allowed_obj))] += 1

    # ── Step 2: build relabel plan ──
    relabel_plan = {}  # id -> (old_label, new_label)
    for nid, current in nodes.items():
        v = votes.get(nid)
        if not v:
            continue
        winner, win_votes = v.most_common(1)[0]
        current_votes = v.get(current, 0)
        # Relabel only when winner strictly beats current label's support
        if winner != current and win_votes > current_votes:
            relabel_plan[nid] = (current, winner)

    print(f"  {len(relabel_plan):,} nodes to relabel")
    by_change = Counter((o, n) for o, n in relabel_plan.values())
    for (o, n), c in by_change.most_common():
        print(f"    {o} -> {n}: {c:,} nodes")

    # Sample
    print("\n  Sample relabels (first 12):")
    for nid, (o, n) in list(relabel_plan.items())[:12]:
        print(f"    [{o}->{n}] {nid}")

    # ── Step 3: simulate relabel, find edges still violating ──
    new_type = dict(nodes)
    for nid, (_, n) in relabel_plan.items():
        new_type[nid] = n

    to_drop = []
    self_loops = []
    for sub, rt, obj, eid in edges:
        if sub == obj:
            self_loops.append((sub, rt, obj, eid))
            continue
        if rt not in SCHEMA:
            continue
        allowed_sub, allowed_obj = SCHEMA[rt]
        st, ot = new_type.get(sub), new_type.get(obj)
        if st not in allowed_sub or ot not in allowed_obj:
            to_drop.append((sub, rt, obj, eid, st, ot))

    print(f"\n  Self-loop edges to drop: {len(self_loops)}")
    for sub, rt, _, _ in self_loops:
        print(f"    {sub} -[{rt}]-> itself")

    print(f"\n  Edges still violating after relabel (to drop): {len(to_drop)}")
    drop_patterns = Counter((rt, st, ot) for _, rt, _, _, st, ot in to_drop)
    for (rt, st, ot), c in drop_patterns.most_common():
        print(f"    {rt}: {st}->{ot} ({c})")
    print("\n  Sample edges to drop (first 10):")
    for sub, rt, obj, _, st, ot in to_drop[:10]:
        print(f"    [{st}->{ot}] {sub} -[{rt}]-> {obj}")

    # ── Summary ──
    print(f"\n=== Cleanup Summary ===")
    print(f"  Schema expansion makes valid:  ~139 modulation edges")
    print(f"  Node relabels:                 {len(relabel_plan):,} nodes")
    print(f"  Edges to drop (self-loops):    {len(self_loops)}")
    print(f"  Edges to drop (mis-predicated):{len(to_drop)}")
    print(f"  Net edges removed:             {len(self_loops) + len(to_drop)}")

    if args.dry_run:
        print(f"\nDRY RUN - no writes. Use --apply to execute.")
        driver.close()
        return

    # ── Apply ──
    print(f"\n=== Applying changes ===")
    with driver.session() as s:
        # Relabel nodes
        print(f"Relabelling {len(relabel_plan):,} nodes...")
        relabels = [{"id": nid, "old": o, "new": n}
                    for nid, (o, n) in relabel_plan.items()]
        for i in range(0, len(relabels), 200):
            chunk = relabels[i:i+200]
            # Group by (old,new) since label names can't be parameterised
            for (o, n) in set((r["old"], r["new"]) for r in chunk):
                ids = [r["id"] for r in chunk if r["old"] == o and r["new"] == n]
                s.run(f"""
                    UNWIND $ids AS nid
                    MATCH (x {{id: nid}})
                    REMOVE x:`{o}` SET x:`{n}`, x.type = $newtype
                """, ids=ids, newtype=n).consume()
        print("  done")

        # Drop self-loops + mis-predicated edges
        all_drop_eids = ([e[3] for e in self_loops] +
                         [e[3] for e in to_drop])
        print(f"Dropping {len(all_drop_eids):,} edges...")
        for i in range(0, len(all_drop_eids), 500):
            chunk = all_drop_eids[i:i+500]
            s.run("""
                UNWIND $eids AS eid
                MATCH ()-[r]->() WHERE elementId(r) = eid
                DELETE r
            """, eids=chunk).consume()
        print("  done")

        # Verify
        print(f"\n=== Post-fix verification ===")
        n_nodes = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        n_edges = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        loops = s.run("MATCH (n)-[r]->(n) RETURN count(r) AS c").single()["c"]
        print(f"  Total nodes: {n_nodes:,}")
        print(f"  Total edges: {n_edges:,}")
        print(f"  Self-loops:  {loops}")

        viol = 0
        for rt, (asu, aob) in SCHEMA.items():
            if rt in ("INVOLVES", "IS_LOW_FODMAP_FOOD", "MODULATES_CLUSTER"):
                continue
            rows = s.run(f"""
                MATCH (a)-[r:`{rt}`]->(b)
                RETURN labels(a)[0] AS st, labels(b)[0] AS ot, count(*) AS c
            """).data()
            for r in rows:
                if r["st"] not in asu or r["ot"] not in aob:
                    viol += r["c"]
        print(f"  Remaining schema violations (core predicates): {viol}")

    driver.close()
    print(f"\nSchema fix complete.")


if __name__ == "__main__":
    main()
