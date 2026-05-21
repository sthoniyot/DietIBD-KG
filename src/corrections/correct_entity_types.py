#!/usr/bin/env python3
"""
correct_entity_types.py - DietIBD-KG entity-typing correction

A two-phase tool that fixes the entity-typing problem found by
triage_entity_types.py. It rewrites NODE TYPES only; it never edits or
deletes edges - it only REPORTS edges whose endpoints no longer fit the
schema, so you decide whether to drop or re-home them.

PHASE 1 (default) -- python correct_entity_types.py
  * identifies the flagged entities (re-running the triage logic);
  * writes corrections/review_decisions.tsv -- every flagged entity, with an
    editable `decision` column pre-filled with a suggestion;
  * writes corrections/nodes_corrected.tsv with ONLY the high-confidence
    microbe corrections applied;
  * runs a best-effort schema re-validation and reports affected edges.

PHASE 2 -- python correct_entity_types.py --decisions corrections/review_decisions.tsv
  (run after you have reviewed and edited review_decisions.tsv)
  * applies exactly the decisions in that file for every row;
  * writes the final corrections/nodes_corrected.tsv and change_log.tsv;
  * re-validates and writes corrections/edge_violations.tsv.
  (the decisions file is read-only in this phase - your edits are safe.)

IMPORTANT
  * The SCHEMA dict below was reconstructed from the manuscript Methods.
    VERIFY it against your authoritative QA module before relying on the
    edge-validation report, and re-run your existing QA pipeline on
    nodes_corrected.tsv as the final check.
  * `decision` column values: a valid type name (Food, Bioactive, Microbe,
    IBD_Outcome, Pathway) re-types the entity; `keep` or blank leaves it.

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

VALID_TYPES = {"Food", "Bioactive", "Microbe", "IBD_Outcome", "Pathway"}

# ===========================================================================
# FINAL (QA-revised) SCHEMA -- (allowed subject types, allowed object types).
# Reconstructed from the manuscript Methods. >>> VERIFY against your QA module
# before trusting the edge-validation report; adjust any line that is wrong.
# Predicate keys are matched case-insensitively.
# ===========================================================================
SCHEMA = {
    "contains":                   ({"Food"},                       {"Bioactive"}),
    "has_high_fodmap_content_of": ({"Food"},                       {"Bioactive"}),
    "is_low_fodmap_food":         ({"Food"},                       {"Bioactive"}),
    "produces":                   ({"Microbe"},                    {"Bioactive"}),
    "increases_abundance_of":     ({"Food", "Bioactive", "Microbe"}, {"Microbe"}),
    "decreases_abundance_of":     ({"Food", "Bioactive", "Microbe"}, {"Microbe"}),
    "modulates_cluster":          ({"Food"},                       {"Microbe"}),
    "increased_in":               ({"Microbe"},                    {"IBD_Outcome"}),
    "decreased_in":               ({"Microbe"},                    {"IBD_Outcome"}),
    "increases_marker":           ({"Food", "Bioactive", "Microbe"}, {"IBD_Outcome"}),
    "decreases_marker":           ({"Food", "Bioactive", "Microbe"}, {"IBD_Outcome"}),
    "involves":                   ({"Pathway"},                    {"Bioactive"}),
}

# --- triage rules (kept in sync with triage_entity_types.py) ---------------

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
PRODUCT_WORDS = {
    "milk", "extract", "juice", "powder", "oil", "supplement", "fermented",
    "synbiotic", "yogurt", "yoghurt", "cheese", "product", "drink", "broth",
    "diet", "kefir", "tea", "soup", "bread", "flour", "paste", "sauce",
}
COMPOUND_KEYWORDS = {
    "acid", "polyphenol", "flavonoid", "polysaccharide", "peptide",
    "glycoside", "saponin", "alkaloid", "terpene", "sterol", "catechin",
    "carotenoid", "anthocyanin", "metabolite",
}
COMPOUND_SUFFIXES = ("ose", "ol", "ide", "ate")
GREEK = set("αβγδεζηθικλμνξοπρστυφχψω")
DIET_RE = re.compile(r"\bdiet\b|\bdietary pattern\b", re.IGNORECASE)
IUPAC_RE = re.compile(r"\d[,\-]\d|\(\s*[rs]\s*\)\s*-", re.IGNORECASE)


def clean(s):
    return (s or "").replace("\r", "").strip()


def first_token(label):
    toks = re.split(r"[\s]+", label.strip())
    return re.sub(r"[^a-zA-Z]", "", toks[0]).lower() if toks else ""


def has_strain_code(label):
    for tok in re.split(r"[\s]+", label):
        t = tok.strip("()[],.;:")
        if len(t) >= 4 and sum(c.isupper() for c in t) >= 2 \
                and any(c.isdigit() for c in t):
            return True
    return False


def microbe_rules(label, genus_set):
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


# --- I/O -------------------------------------------------------------------

def read_nodes(path):
    rows, header = [], None
    with open(path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh, delimiter="\t")
        header = [clean(c) for c in next(reader)]
        idx = {n: header.index(n) for n in ("id", "label", "type", "origin")
               if n in header}
        for n in ("id", "label", "type"):
            if n not in idx:
                sys.exit(f"ERROR: nodes file missing '{n}' column. Header: {header}")
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
    return rows, header


def degree_counts(edges_path, node_ids):
    deg = Counter()
    try:
        with open(edges_path, "r", encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh, delimiter="\t")
            next(reader, None)
            for raw in reader:
                for cell in raw:
                    c = clean(cell)
                    if c in node_ids:
                        deg[c] += 1
    except FileNotFoundError:
        return None
    return deg


def detect_edge_columns(header):
    h = [c.lower() for c in header]

    def find(cands):
        for cand in cands:                       # exact match first
            if cand in h:
                return h.index(cand)
        for cand in cands:                       # then substring
            for i, name in enumerate(h):
                if cand in name:
                    return i
        return None

    s = find(["subject", "subject_id", "subj", "source", "head", "from"])
    p = find(["predicate", "relation", "edge_type", "rel"])
    o = find(["object", "object_id", "obj", "target", "tail", "to"])
    if None in (s, p, o):
        return None
    return s, p, o


def validate_edges(edges_path, type_map):
    """Return (violations, n_checked, n_unknown_pred) or None if unreadable."""
    try:
        fh = open(edges_path, "r", encoding="utf-8", newline="")
    except FileNotFoundError:
        return None
    with fh:
        reader = csv.reader(fh, delimiter="\t")
        header = [clean(c) for c in next(reader, [])]
        cols = detect_edge_columns(header)
        if cols is None:
            return "no_columns", header
        si, pi, oi = cols
        violations, n_checked, n_unknown = [], 0, 0
        for raw in reader:
            if max(si, pi, oi) >= len(raw):
                continue
            subj, pred, obj = (clean(raw[si]), clean(raw[pi]).lower(),
                               clean(raw[oi]))
            st, ot = type_map.get(subj), type_map.get(obj)
            if st is None or ot is None:
                continue
            if pred not in SCHEMA:
                n_unknown += 1
                continue
            n_checked += 1
            allow_s, allow_o = SCHEMA[pred]
            if st not in allow_s or ot not in allow_o:
                violations.append({
                    "subject_id": subj, "subject_type": st, "predicate": pred,
                    "object_id": obj, "object_type": ot,
                    "reason": (f"subject {st} not in {sorted(allow_s)}"
                               if st not in allow_s
                               else f"object {ot} not in {sorted(allow_o)}"),
                })
        return violations, n_checked, n_unknown


# --- classification --------------------------------------------------------

def classify(llm_nodes, genus_set):
    high, medium, compounds, diets = [], [], [], []
    for n in llm_nodes:
        label, atype = n["label"], n["type"]
        m = microbe_rules(label, genus_set)
        if m and atype != "Microbe":
            words = label.lower().split()
            has_product = any(w in PRODUCT_WORDS for w in words)
            if "genus" in m and len(words) <= 5 and not has_product:
                high.append(n)
            else:
                medium.append(n)
            continue
        if DIET_RE.search(label) and atype == "Food":
            diets.append(n)
            continue
        if compound_rules(label) and atype == "Food":
            compounds.append(n)
    return high, medium, compounds, diets


# --- main ------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nodes", default=DEFAULT_NODES)
    ap.add_argument("--edges", default=DEFAULT_EDGES)
    ap.add_argument("--outdir", default="corrections")
    ap.add_argument("--decisions", default=None,
                    help="Phase 2: path to your edited review_decisions.tsv")
    args = ap.parse_args()

    nodes_path = Path(args.nodes)
    if not nodes_path.exists():
        sys.exit(f"ERROR: nodes file not found: {nodes_path}")

    nodes, header = read_nodes(nodes_path)
    for n in nodes:
        n["is_llm"] = n["id"].startswith("LLM:")
    curated = [n for n in nodes if not n["is_llm"]]
    llm = [n for n in nodes if n["is_llm"]]

    genus_set = set(BUILTIN_GENERA)
    for n in curated:
        if n["type"] == "Microbe":
            g = first_token(n["label"])
            if len(g) >= 4:
                genus_set.add(g)

    high, medium, compounds, diets = classify(llm, genus_set)
    deg = degree_counts(Path(args.edges), {n["id"] for n in nodes})
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    phase2 = args.decisions is not None

    # ----- build the set of corrections ------------------------------------
    corrections = {}        # id -> new_type
    if not phase2:
        # PHASE 1: apply only the high-confidence microbe corrections
        for n in high:
            corrections[n["id"]] = "Microbe"
    else:
        # PHASE 2: apply exactly what the decisions file says
        dpath = Path(args.decisions)
        if not dpath.exists():
            sys.exit(f"ERROR: decisions file not found: {dpath}")
        cur_type = {n["id"]: n["type"] for n in nodes}
        with open(dpath, "r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            for row in reader:
                nid = clean(row.get("id", ""))
                dec = clean(row.get("decision", ""))
                if not nid or nid not in cur_type:
                    continue
                if dec in VALID_TYPES and dec != cur_type[nid]:
                    corrections[nid] = dec
                elif dec and dec.lower() != "keep" and dec not in VALID_TYPES:
                    print(f"  WARNING: row '{nid}' has unrecognised decision "
                          f"'{dec}' - ignored.")

    # ----- write the review template (PHASE 1 only) ------------------------
    if not phase2:
        suggestion = {"high_confidence_microbe": "Microbe",
                      "medium_microbe": "Microbe",
                      "compound_candidate": "Bioactive",
                      "dietary_pattern": "keep"}
        buckets = ([("high_confidence_microbe", n) for n in high]
                   + [("medium_microbe", n) for n in medium]
                   + [("compound_candidate", n) for n in compounds]
                   + [("dietary_pattern", n) for n in diets])
        with open(outdir / "review_decisions.tsv", "w", encoding="utf-8",
                  newline="") as fh:
            w = csv.writer(fh, delimiter="\t")
            w.writerow(["id", "label", "current_type", "bucket", "degree",
                        "suggested_decision", "decision"])
            for bucket, n in sorted(
                    buckets, key=lambda x: -(deg.get(x[1]["id"], 0) if deg else 0)):
                sug = suggestion[bucket]
                w.writerow([n["id"], n["label"], n["type"], bucket,
                            deg.get(n["id"], 0) if deg else "n/a", sug, sug])

    # ----- apply corrections, write nodes_corrected ------------------------
    type_map = {}
    change_log = []
    with open(outdir / "nodes_corrected.tsv", "w", encoding="utf-8",
              newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(header)
        col = {name: header.index(name) for name in header}
        for n in nodes:
            new_type = corrections.get(n["id"], n["type"])
            type_map[n["id"]] = new_type
            if new_type != n["type"]:
                change_log.append((n["id"], n["label"], n["type"], new_type))
            row = [""] * len(header)
            row[col["id"]] = n["id"]
            row[col["label"]] = n["label"]
            row[col["type"]] = new_type
            if "origin" in col:
                row[col["origin"]] = n["origin"]
            w.writerow(row)

    with open(outdir / "change_log.tsv", "w", encoding="utf-8",
              newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["id", "label", "old_type", "new_type"])
        for rec in change_log:
            w.writerow(rec)

    # ----- validate edges on the corrected graph ---------------------------
    val = validate_edges(Path(args.edges), type_map)

    # ----- report ----------------------------------------------------------
    line = "=" * 64
    print(line)
    print(f" DietIBD-KG entity-typing correction - "
          f"{'PHASE 2 (applying decisions)' if phase2 else 'PHASE 1 (auto only)'}")
    print(line)
    print(f"Nodes file : {nodes_path}")
    print(f"Total entities {len(nodes):,}  "
          f"(curated {len(curated):,} / literature {len(llm):,})")
    print()
    print("Flagged entities:")
    print(f"  high-confidence microbes : {len(high):,}")
    print(f"  medium-confidence        : {len(medium):,}")
    print(f"  compound candidates      : {len(compounds):,}")
    print(f"  dietary patterns         : {len(diets):,}")
    print()
    print(f"Corrections applied this run : {len(change_log):,}")
    for t, c in Counter(nt for _, _, _, nt in change_log).most_common():
        print(f"    re-typed to {t:<12}: {c:,}")

    print()
    if val is None:
        print("Edge validation : edges file not found - skipped.")
        print(f"  (looked for {args.edges}; pass --edges, or run your QA module)")
    elif isinstance(val, tuple) and val and val[0] == "no_columns":
        print("Edge validation : could not identify subject/predicate/object")
        print(f"  columns in the edges header: {val[1]}")
        print("  -> skipped. Run your own QA pipeline on nodes_corrected.tsv.")
    else:
        violations, n_checked, n_unknown = val
        with open(outdir / "edge_violations.tsv", "w", encoding="utf-8",
                  newline="") as fh:
            w = csv.writer(fh, delimiter="\t")
            w.writerow(["subject_id", "subject_type", "predicate",
                        "object_id", "object_type", "reason"])
            for v in violations:
                w.writerow([v["subject_id"], v["subject_type"], v["predicate"],
                            v["object_id"], v["object_type"], v["reason"]])
        print(f"Edge validation : {n_checked:,} edges checked against the schema")
        print(f"  schema-INVALID after correction : {len(violations):,}")
        if n_unknown:
            print(f"  edges with a predicate not in SCHEMA (skipped): {n_unknown:,}")
        for pred, c in Counter(v["predicate"] for v in violations).most_common():
            print(f"    {pred:<26}: {c:,}")
        print("  >>> these edges need a decision: drop them, or re-home the")
        print("      endpoint. The script does NOT touch edges.")

    print()
    print(f"Files written to {outdir}/ :")
    written = ["nodes_corrected.tsv", "change_log.tsv"]
    if not phase2:
        written.insert(0, "review_decisions.tsv")
    if val is not None and not (isinstance(val, tuple) and val[0] == "no_columns"):
        written.append("edge_violations.tsv")
    for f in written:
        print(f"  {f}")
    print(line)
    if not phase2:
        print("NEXT: review and edit corrections/review_decisions.tsv (the")
        print("`decision` column), then re-run with:")
        print("  python correct_entity_types.py --decisions "
              "corrections/review_decisions.tsv")
    else:
        print("NEXT: re-run your authoritative QA pipeline on")
        print("nodes_corrected.tsv; resolve any edges in edge_violations.tsv;")
        print("re-train embeddings only if the edge set changed.")
    print(line)


if __name__ == "__main__":
    main()
