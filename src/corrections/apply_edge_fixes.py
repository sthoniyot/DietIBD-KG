#!/usr/bin/env python3
"""
apply_edge_fixes.py - resolve the schema-violating edges found by Phase 2.

Reads edges.tsv and corrections/edge_violations.tsv and applies the agreed
resolution to every violating edge:

  * RE-HOME (9 edges): a microbe extracted as `contains` a metabolite is
    corrected to `produces` (Microbe -> Bioactive, valid). Real data, kept.
  * DROP (the rest): genuine mis-extractions with no valid predicate
    (e.g. "polysaccharide contains short-chain fatty acid", where the SCFA
    is a fermentation product, not a constituent; circular/structural edges).

Writes corrections/edges_corrected.tsv plus a log. Read-only on the input.
The edge file's columns are auto-detected.

Usage:
    python apply_edge_fixes.py
    python apply_edge_fixes.py --edges release/dietibdkg-v1.0.0/edges.tsv

Standard library only.
"""
import argparse
import csv
import sys
from pathlib import Path

DEFAULT_EDGES = "release/dietibdkg-v1.0.0/edges.tsv"
DEFAULT_VIOLATIONS = "corrections/edge_violations.tsv"

# The 9 (subject_id, object_id) pairs to re-home from `contains` to `produces`.
REHOME = {
    ("LLM:bacillus_coagulans_mtcc5856", "LLM:polysaccharide-degrading_enzymes"),
    ("LLM:bifidobacterium_bifidum_h3-r2", "LLM:acetic_acid"),
    ("LLM:clostridium_butyricum_c1-6", "LLM:butyric_acid"),
    ("LLM:escherichia_coli_nissle_1917_expressing_elafin", "LLM:elafin"),
    ("LLM:lactobacillus_rhamnosus_1_0320", "LLM:carboxylic_acid"),
    ("LLM:latilactobacillus_sakei_ccfm1267", "LLM:carbohydrate-active_enzymes"),
    ("LLM:propionibacterium_freudenreichii_b1", "LLM:propionic_acid"),
    ("LLM:saccharomyces_boulardii", "LLM:polysaccharide"),
    ("LLM:saccharomyces_boulardii", "LLM:polypeptide"),
}


def clean(s):
    return (s or "").replace("\r", "").strip()


def detect_cols(header):
    h = [c.lower() for c in header]

    def find(cands):
        for c in cands:
            if c in h:
                return h.index(c)
        for c in cands:
            for i, n in enumerate(h):
                if c in n:
                    return i
        return None

    s = find(["subject", "subject_id", "subj", "source", "head", "from"])
    p = find(["predicate", "relation", "edge_type", "rel"])
    o = find(["object", "object_id", "obj", "target", "tail", "to"])
    return (s, p, o) if None not in (s, p, o) else None


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--edges", default=DEFAULT_EDGES)
    ap.add_argument("--violations", default=DEFAULT_VIOLATIONS)
    ap.add_argument("--out", default="corrections/edges_corrected.tsv")
    args = ap.parse_args()

    # --- read the violating edges -----------------------------------------
    broken = set()                       # (subject, predicate_lower, object)
    with open(args.violations, encoding="utf-8", newline="") as fh:
        r = csv.reader(fh, delimiter="\t")
        next(r, None)                    # header
        for row in r:
            if len(row) >= 4:
                # columns: subject_id, subject_type, predicate, object_id, ...
                broken.add((clean(row[0]), clean(row[2]).lower(), clean(row[3])))

    rehome_keys = {(s, p, o) for (s, p, o) in broken if (s, o) in REHOME}
    drop_keys = broken - rehome_keys
    print(f"edge_violations.tsv : {len(broken)} violating edges "
          f"({len(rehome_keys)} to re-home, {len(drop_keys)} to drop)")

    # --- read edges --------------------------------------------------------
    edges_path = Path(args.edges)
    if not edges_path.exists():
        sys.exit(f"ERROR: edges file not found: {edges_path}")
    with open(edges_path, encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh, delimiter="\t"))
    if not rows:
        sys.exit("ERROR: edges file is empty.")

    header = [clean(c) for c in rows[0]]
    cols = detect_cols(header)
    if cols is None:
        sys.exit(f"ERROR: could not detect subject/predicate/object columns.\n"
                 f"Header seen: {header}")
    si, pi, oi = cols

    # --- apply -------------------------------------------------------------
    out_rows = [rows[0]]
    n_rehomed = n_dropped = n_kept = 0
    rehome_log, drop_log = [], []
    seen_rehome, seen_drop = set(), set()

    for raw in rows[1:]:
        if not raw or max(si, pi, oi) >= len(raw):
            out_rows.append(raw)
            n_kept += 1
            continue
        s, p_raw, o = clean(raw[si]), clean(raw[pi]), clean(raw[oi])
        key = (s, p_raw.lower(), o)
        if key in rehome_keys:
            new = list(raw)
            new[pi] = "PRODUCES" if p_raw.isupper() else "produces"
            out_rows.append(new)
            n_rehomed += 1
            rehome_log.append((s, o))
            seen_rehome.add(key)
        elif key in drop_keys:
            n_dropped += 1
            drop_log.append((s, p_raw, o))
            seen_drop.add(key)
        else:
            out_rows.append(raw)
            n_kept += 1

    # --- write -------------------------------------------------------------
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh, delimiter="\t").writerows(out_rows)

    log_path = out_path.parent / "edge_fixes_log.tsv"
    with open(log_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["action", "subject", "predicate", "object"])
        for s, o in rehome_log:
            w.writerow(["rehomed_to_produces", s, "contains->produces", o])
        for s, p, o in drop_log:
            w.writerow(["dropped", s, p, o])

    # --- report ------------------------------------------------------------
    line = "=" * 60
    print(line)
    print(f"edges in  : {len(rows) - 1:,}")
    print(f"  re-homed (contains -> produces) : {n_rehomed}")
    print(f"  dropped                         : {n_dropped}")
    print(f"  unchanged                       : {n_kept:,}")
    print(f"edges out : {len(out_rows) - 1:,}")
    print(line)

    missing_rehome = rehome_keys - seen_rehome
    missing_drop = drop_keys - seen_drop
    if missing_rehome or missing_drop:
        print("WARNING: some violating edges were not found in the edge file:")
        for k in missing_rehome | missing_drop:
            print(f"  {k}")
        print("Check that --edges points to the same file Phase 2 validated.")
    else:
        print("All violating edges accounted for.")
    print(f"Written: {out_path}")
    print(f"         {log_path}")
    print(line)
    print("NEXT: use nodes_corrected.tsv + edges_corrected.tsv, then re-run")
    print("your QA pipeline (it should now report 0 schema violations) and")
    print("re-train embeddings.")


if __name__ == "__main__":
    main()
