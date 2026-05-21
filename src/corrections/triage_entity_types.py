#!/usr/bin/env python3
"""
triage_entity_types.py - DietIBD-KG entity-typing triage

Scans the released nodes file and flags literature-layer (LLM:) entities whose
model-assigned type is likely incorrect - primarily microbial strains and
isolated compounds filed under the Food type - so the extent of the typing
issue can be quantified before deciding how to correct it.

This is a TRIAGE tool. It produces REVIEW CANDIDATES, not final decisions:
  * the microbe rules are high precision and reasonable recall (they use a
    genus set derived from the graph's own curated Microbe entities);
  * the compound rules are conservative heuristics - they will MISS
    trivially-named compounds (e.g. "Icariin", "Resolvin D1"), so the compound
    count is a LOWER BOUND. A thorough compound audit needs an LLM pass.

The script is READ-ONLY on the graph: it modifies nothing and only writes
review TSVs into the output directory.

Usage:
    python triage_entity_types.py
    python triage_entity_types.py --nodes release/dietibdkg-v1.0.0/nodes.tsv
    python triage_entity_types.py --edges release/dietibdkg-v1.0.0/edges.tsv
    python triage_entity_types.py --outdir typing_triage

Standard library only - no installation required.
"""
import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_NODES = "release/dietibdkg-v1.0.0/nodes.tsv"
DEFAULT_EDGES = "release/dietibdkg-v1.0.0/edges.tsv"

# Common gut / probiotic / IBD-relevant genera. Used as a fallback in case the
# curated layer's genus coverage is thin; the script ALSO derives genera from
# the curated Microbe entities present in the graph itself.
BUILTIN_GENERA = {
    "lactobacillus", "bifidobacterium", "bacteroides", "escherichia",
    "clostridium", "clostridioides", "faecalibacterium", "akkermansia",
    "roseburia", "prevotella", "streptococcus", "enterococcus",
    "ruminococcus", "eubacterium", "blautia", "lactococcus", "saccharomyces",
    "fusobacterium", "klebsiella", "proteus", "salmonella", "shigella",
    "helicobacter", "campylobacter", "veillonella", "parabacteroides",
    "alistipes", "coprococcus", "dorea", "collinsella", "odoribacter",
    "bilophila", "desulfovibrio", "pediococcus", "leuconostoc", "weissella",
    "enterobacter", "citrobacter", "pseudomonas", "staphylococcus",
    "bacillus", "anaerostipes", "butyrivibrio", "megamonas", "megasphaera",
    "sutterella", "oscillospira", "christensenella", "subdoligranulum",
    "intestinimonas", "holdemania", "turicibacter", "lachnospira",
    "phascolarctobacterium", "anaerobutyricum", "agathobacter",
}

# Words that mean a name is probably NOT a bare microbe even if a genus
# appears in it (e.g. "Lactobacillus-fermented milk").
PRODUCT_WORDS = {
    "milk", "extract", "juice", "powder", "oil", "supplement", "fermented",
    "synbiotic", "yogurt", "yoghurt", "cheese", "product", "drink", "broth",
    "diet", "kefir", "tea", "soup", "bread", "flour", "paste", "sauce",
}

# Substrings suggestive of an isolated chemical compound.
COMPOUND_KEYWORDS = {
    "acid", "polyphenol", "flavonoid", "polysaccharide", "peptide",
    "glycoside", "saponin", "alkaloid", "terpene", "sterol", "catechin",
    "carotenoid", "anthocyanin", "metabolite",
}
# Conservative chemical suffixes, matched on the final word (length >= 5).
COMPOUND_SUFFIXES = ("ose", "ol", "ide", "ate")
GREEK = set("αβγδεζηθικλμνξοπρστυφχψω")

DIET_RE = re.compile(r"\bdiet\b|\bdietary pattern\b", re.IGNORECASE)
IUPAC_RE = re.compile(r"\d[,\-]\d|\(\s*[rs]\s*\)\s*-", re.IGNORECASE)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def clean(s):
    """Strip carriage returns and surrounding whitespace from a field."""
    return (s or "").replace("\r", "").strip()


def norm(s):
    """Loose normalized form for name-collision detection."""
    s = s.lower().strip()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def first_token(label):
    toks = re.split(r"[\s]+", label.strip())
    if not toks:
        return ""
    return re.sub(r"[^a-zA-Z]", "", toks[0]).lower()


def has_strain_code(label):
    """A token with >=2 uppercase letters AND >=1 digit, length >=4."""
    for tok in re.split(r"[\s]+", label):
        t = tok.strip("()[],.;:")
        if len(t) < 4:
            continue
        uppers = sum(c.isupper() for c in t)
        digits = sum(c.isdigit() for c in t)
        if uppers >= 2 and digits >= 1:
            return True
    return False


def microbe_rules(label, genus_set):
    """Return the set of microbe-indicating rules a label triggers."""
    hits = set()
    low = label.lower()
    if first_token(label) in genus_set:
        hits.add("genus")
    if has_strain_code(label):
        hits.add("strain_code")
    if "consortium" in low or re.search(r"\bsp\.?\b|\bspp\.?\b", low):
        hits.add("consortium/sp.")
    return hits


def compound_rules(label):
    """Return the set of compound-indicating rules a label triggers."""
    hits = set()
    low = label.lower()
    if any(ch in GREEK for ch in label):
        hits.add("greek_letter")
    if any(k in low for k in COMPOUND_KEYWORDS):
        hits.add("compound_keyword")
    if IUPAC_RE.search(label):
        hits.add("iupac_pattern")
    toks = [t for t in re.split(r"[\s]+", low) if t]
    if toks:
        last = re.sub(r"[^a-z]", "", toks[-1])
        if len(last) >= 5 and last.endswith(COMPOUND_SUFFIXES):
            hits.add("chemical_suffix")
    return hits


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def read_nodes(path):
    rows = []
    with open(path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh, delimiter="\t")
        header = [clean(c) for c in next(reader)]
        idx = {name: header.index(name) for name in ("id", "label", "type", "origin")
               if name in header}
        for name in ("id", "label", "type"):
            if name not in idx:
                sys.exit(f"ERROR: nodes file is missing a '{name}' column. "
                         f"Header seen: {header}")
        for raw in reader:
            if not raw:
                continue
            rows.append({
                "id": clean(raw[idx["id"]]),
                "label": clean(raw[idx["label"]]),
                "type": clean(raw[idx["type"]]),
                "origin": clean(raw[idx["origin"]]) if "origin" in idx
                          and idx["origin"] < len(raw) else "",
            })
    return rows


def degree_counts(edges_path, node_ids):
    """Column-agnostic degree: count edge fields equal to a known node id."""
    deg = Counter()
    try:
        with open(edges_path, "r", encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh, delimiter="\t")
            next(reader, None)  # skip header
            for raw in reader:
                for cell in raw:
                    c = clean(cell)
                    if c in node_ids:
                        deg[c] += 1
    except FileNotFoundError:
        return None
    return deg


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nodes", default=DEFAULT_NODES)
    ap.add_argument("--edges", default=DEFAULT_EDGES)
    ap.add_argument("--outdir", default="typing_triage")
    args = ap.parse_args()

    nodes_path = Path(args.nodes)
    if not nodes_path.exists():
        sys.exit(f"ERROR: nodes file not found: {nodes_path}\n"
                 f"Pass the correct path with --nodes.")

    nodes = read_nodes(nodes_path)
    for n in nodes:
        n["is_llm"] = n["id"].startswith("LLM:")

    curated = [n for n in nodes if not n["is_llm"]]
    llm = [n for n in nodes if n["is_llm"]]

    # genus reference set: first token of every curated Microbe label
    genus_set = set(BUILTIN_GENERA)
    for n in curated:
        if n["type"] == "Microbe":
            g = first_token(n["label"])
            if len(g) >= 4:
                genus_set.add(g)

    # degree (optional)
    deg = degree_counts(Path(args.edges), {n["id"] for n in nodes})

    # classify LLM entities
    flagged_microbes, flagged_compounds, flagged_diets = [], [], []
    for n in llm:
        label, atype = n["label"], n["type"]
        m_hits = microbe_rules(label, genus_set)
        if m_hits and atype != "Microbe":
            ntok = len(label.split())
            has_product = any(w in label.lower().split() for w in PRODUCT_WORDS)
            conf = ("high" if ("genus" in m_hits and ntok <= 5
                               and not has_product) else "medium")
            flagged_microbes.append((n, conf, sorted(m_hits)))
            continue
        if DIET_RE.search(label) and atype == "Food":
            flagged_diets.append((n, "n/a", ["diet_in_name"]))
            continue
        c_hits = compound_rules(label)
        if c_hits and atype == "Food":
            flagged_compounds.append((n, "review", sorted(c_hits)))

    # name collisions across types
    by_norm = defaultdict(set)
    for n in nodes:
        by_norm[norm(n["label"])].add(n["type"])
    collisions = {k: v for k, v in by_norm.items() if len(v) > 1 and k}

    # ---- write review files ------------------------------------------------
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    def write_tsv(fname, flagged):
        with open(outdir / fname, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, delimiter="\t")
            w.writerow(["id", "label", "assigned_type", "confidence",
                        "rules", "degree"])
            for n, conf, rules in sorted(
                    flagged, key=lambda x: -(deg.get(x[0]["id"], 0) if deg else 0)):
                w.writerow([n["id"], n["label"], n["type"], conf,
                            ";".join(rules),
                            deg.get(n["id"], 0) if deg else "n/a"])

    write_tsv("flagged_microbes.tsv", flagged_microbes)
    write_tsv("flagged_compounds.tsv", flagged_compounds)
    write_tsv("flagged_diets.tsv", flagged_diets)
    with open(outdir / "name_collisions.tsv", "w", encoding="utf-8",
              newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["normalized_name", "types"])
        for k, v in sorted(collisions.items()):
            w.writerow([k, ";".join(sorted(v))])

    # ---- report ------------------------------------------------------------
    def deg_sum(flagged):
        return sum(deg.get(n["id"], 0) for n, _, _ in flagged) if deg else None

    line = "=" * 64
    print(line)
    print(" DietIBD-KG entity-typing triage")
    print(line)
    print(f"Nodes file : {nodes_path}")
    print(f"Total entities          : {len(nodes):,}")
    print(f"  curated-layer (ontology IDs) : {len(curated):,}")
    print(f"  literature-layer (LLM: IDs)  : {len(llm):,}")
    print(f"Genus reference set     : {len(genus_set):,} genera "
          f"(curated Microbe labels + builtin list)")
    if deg is None:
        print("Edges file              : not found - degree column = n/a")
        print(f"  (looked for: {args.edges}; pass --edges to enable degree)")
    else:
        print(f"Edges file              : {args.edges}")

    print()
    print("LITERATURE-LAYER ENTITIES BY ASSIGNED TYPE")
    for t, c in Counter(n["type"] for n in llm).most_common():
        print(f"  {t:<14} {c:,}")

    mh = sum(1 for _, c, _ in flagged_microbes if c == "high")
    mm = sum(1 for _, c, _ in flagged_microbes if c == "medium")
    print()
    print("--- FLAGGED: likely misfiled MICROBES (assigned type != Microbe) ---")
    print(f"  total flagged : {len(flagged_microbes):,}")
    print(f"    high confidence (name is a bare microbe) : {mh:,}")
    print(f"    medium confidence (microbe in a product) : {mm:,}")
    by_at = Counter(n["type"] for n, _, _ in flagged_microbes)
    for t, c in by_at.most_common():
        print(f"    currently typed {t:<12}: {c:,}")
    if deg is not None:
        print(f"  these entities participate in {deg_sum(flagged_microbes):,} "
              f"edge endpoints")

    print()
    print("--- FLAGGED: possible misfiled COMPOUNDS (assigned type == Food) ---")
    print(f"  total flagged : {len(flagged_compounds):,}   "
          f"[LOWER BOUND - heuristic, review required]")
    rule_ct = Counter()
    for _, _, rules in flagged_compounds:
        rule_ct.update(rules)
    for r, c in rule_ct.most_common():
        print(f"    rule {r:<18}: {c:,}")
    if deg is not None:
        print(f"  these entities participate in {deg_sum(flagged_compounds):,} "
              f"edge endpoints")

    print()
    print("--- FLAGGED: dietary patterns typed as Food (name contains 'diet') ---")
    print(f"  total : {len(flagged_diets):,}   "
          f"[arguably acceptable as coarse Food nodes - your call]")

    print()
    print("--- CROSS-LAYER NAME COLLISIONS (same name, >1 assigned type) ---")
    print(f"  {len(collisions):,} normalized names appear under multiple types")

    print()
    print(f"Review files written to: {outdir}/")
    for f in ("flagged_microbes.tsv", "flagged_compounds.tsv",
              "flagged_diets.tsv", "name_collisions.tsv"):
        print(f"  {f}")

    print(line)
    print("SUMMARY")
    print(f"  High-confidence misfiled microbes : {mh:,} entities  "
          f"(indefensible - a reviewer will flag these)")
    print(f"  Medium-confidence microbe-related : {mm:,} entities  (review)")
    print(f"  Possible misfiled compounds       : {len(flagged_compounds):,} "
          f"entities  (lower bound - review)")
    print(f"  Dietary patterns typed as Food    : {len(flagged_diets):,} "
          f"entities  (decide)")
    print(line)
    print("NOTE: this is a triage tool. Inspect the TSVs before acting; the")
    print("microbe flags are reliable, the compound flags undercount.")


if __name__ == "__main__":
    main()
