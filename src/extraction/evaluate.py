"""Evaluate LLM extraction against gold-standard annotations.

v2: improved fuzzy matching for entity names:
  - Greek letter normalization (β↔beta, α↔alpha, γ↔gamma, etc.)
  - Underscore-to-space normalization for taxonomic names like
    "Eubacterium_coprostanoligenes_group" matching "Eubacterium"
  - Trailing/leading "the", "a", "an" stripped
  - Singular/plural collapsing on final 's'

Usage:
    python src/extraction/evaluate.py --gold dev --llm-version v3
"""
import argparse
import csv
import re
from collections import defaultdict, Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED = PROJECT_ROOT / "data" / "processed"
EXTRACTIONS = PROCESSED / "llm_extractions"
REPORTS = PROJECT_ROOT / "reports" / "phase_c_stage4"
REPORTS.mkdir(parents=True, exist_ok=True)

ALLOWED_PREDICATES = {
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

# Greek letter to spelled-out form (for entity matching)
GREEK_NORMALIZE = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta",
    "ε": "epsilon", "ζ": "zeta", "η": "eta", "θ": "theta",
    "ι": "iota", "κ": "kappa", "λ": "lambda", "μ": "mu",
    "ν": "nu", "ξ": "xi", "ο": "omicron", "π": "pi",
    "ρ": "rho", "σ": "sigma", "τ": "tau", "υ": "upsilon",
    "φ": "phi", "χ": "chi", "ψ": "psi", "ω": "omega",
    # Uppercase
    "Α": "alpha", "Β": "beta", "Γ": "gamma", "Δ": "delta",
    "Ε": "epsilon", "Π": "pi", "Σ": "sigma",
}

# Stop words at start/end of entity names
LEADING_STOPS = {"the", "a", "an"}

# Disease name canonicalization (common abbreviations)
DISEASE_CANON = {
    "uc": "ulcerative colitis",
    "cd": "crohn s disease",
    "ibd": "inflammatory bowel disease",
    "ibs": "irritable bowel syndrome",
    "crohn disease": "crohn s disease",
    "crohns disease": "crohn s disease",
}


def normalize_name(name):
    """Lowercase, normalize Greek letters and underscores, collapse spaces."""
    if not name or name == "-":
        return ""
    s = name.lower().strip()
    # Normalize Greek letters BEFORE removing non-word chars
    for greek, latin in GREEK_NORMALIZE.items():
        s = s.replace(greek, latin)
    # Replace underscores with spaces (Eubacterium_coprostanoligenes → Eubacterium coprostanoligenes)
    s = s.replace("_", " ")
    # Strip punctuation except hyphen
    s = re.sub(r"[^\w\s-]", " ", s)
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    # Strip leading stop words
    tokens = s.split()
    while tokens and tokens[0] in LEADING_STOPS:
        tokens.pop(0)
    s = " ".join(tokens)
    # Apply disease canonicalization
    if s in DISEASE_CANON:
        s = DISEASE_CANON[s]
    return s


def names_match(a, b):
    """Fuzzy entity name match.
    
    Tiers:
    1. Exact normalized match
    2. Containment (one is substring of other, len > 4)
    3. Token overlap Jaccard >= 0.6
    4. Singular/plural collapse on final 's'
    """
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # Try singular/plural collapse on each
    na_singular = na[:-1] if na.endswith("s") and len(na) > 3 else na
    nb_singular = nb[:-1] if nb.endswith("s") and len(nb) > 3 else nb
    if na_singular == nb_singular:
        return True
    # Containment
    if (len(na) > 4 and na in nb) or (len(nb) > 4 and nb in na):
        return True
    if (len(na_singular) > 4 and na_singular in nb_singular) or \
       (len(nb_singular) > 4 and nb_singular in na_singular):
        return True
    # Token Jaccard
    ta, tb = set(na.split()), set(nb.split())
    if not ta or not tb:
        return False
    jaccard = len(ta & tb) / len(ta | tb)
    return jaccard >= 0.6


def triples_match(g, l):
    """Match gold to LLM triple. Same predicate + fuzzy entity name match."""
    if g["predicate"] != l["predicate"]:
        return False
    return names_match(g["subject_name"], l["subject_name"]) and \
           names_match(g["object_name"], l["object_name"])


def load_triples(path, real_only=True):
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    if real_only:
        return [r for r in rows if r["predicate"] not in ("NONE", "")]
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", choices=["dev", "test"], required=True)
    parser.add_argument("--llm-version", required=True)
    args = parser.parse_args()

    gold_path = PROCESSED / f"gold_split_{args.gold}.tsv"
    llm_path = EXTRACTIONS / f"extractions_{args.gold}_{args.llm_version}.tsv"
    report_path = REPORTS / f"eval_{args.gold}_{args.llm_version}.md"

    print(f"Gold:   {gold_path}")
    print(f"LLM:    {llm_path}")
    print(f"Report: {report_path}\n")

    with open(PROCESSED / "gold_standard_to_annotate.tsv", encoding="utf-8") as f:
        source = {r["annot_id"]: r for r in csv.DictReader(f, delimiter="\t")}

    gold_all = load_triples(gold_path, real_only=False)
    llm_all = load_triples(llm_path, real_only=False)

    gold_by_aid = defaultdict(list)
    llm_by_aid = defaultdict(list)
    for r in gold_all:
        gold_by_aid[r["annot_id"]].append(r)
    for r in llm_all:
        llm_by_aid[r["annot_id"]].append(r)

    abstracts = sorted(gold_by_aid.keys())
    print(f"Evaluating {len(abstracts)} abstracts\n")

    tp = []; fp = []; fn = []
    type_violations = []
    matched_llm = set()

    for aid in abstracts:
        g_real = [r for r in gold_by_aid[aid] if r["predicate"] not in ("NONE", "")]
        l_real = [r for r in llm_by_aid.get(aid, []) if r["predicate"] not in ("NONE", "")]

        for li, l in enumerate(l_real):
            expected = ALLOWED_PREDICATES.get(l["predicate"])
            if expected and (l["subject_type"], l["object_type"]) != expected:
                type_violations.append((aid, l))

        for g in g_real:
            matched = False
            for li, l in enumerate(l_real):
                if (aid, li) in matched_llm:
                    continue
                if triples_match(g, l):
                    tp.append((aid, g, l))
                    matched_llm.add((aid, li))
                    matched = True
                    break
            if not matched:
                fn.append((aid, g))

        for li, l in enumerate(l_real):
            if (aid, li) not in matched_llm:
                fp.append((aid, l))

    n_tp = len(tp); n_fp = len(fp); n_fn = len(fn)
    precision = n_tp / (n_tp + n_fp) if (n_tp + n_fp) > 0 else 0
    recall = n_tp / (n_tp + n_fn) if (n_tp + n_fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    pred_tp = Counter(g["predicate"] for _, g, _ in tp)
    pred_fp = Counter(l["predicate"] for _, l in fp)
    pred_fn = Counter(g["predicate"] for _, g in fn)
    all_preds = set(pred_tp) | set(pred_fp) | set(pred_fn)

    stratum_tp = Counter(source[a]["stratum"] for a, _, _ in tp if a in source)
    stratum_fp = Counter(source[a]["stratum"] for a, _ in fp if a in source)
    stratum_fn = Counter(source[a]["stratum"] for a, _ in fn if a in source)
    all_strata = set(stratum_tp) | set(stratum_fp) | set(stratum_fn)

    none_correct = 0; none_violated = 0; extracted_in_none = 0
    for aid in abstracts:
        gold_is_none = all(r["predicate"] in ("NONE", "") for r in gold_by_aid[aid])
        llm_is_none = all(r["predicate"] in ("NONE", "") for r in llm_by_aid.get(aid, []))
        if gold_is_none:
            if llm_is_none:
                none_correct += 1
            else:
                none_violated += 1
                extracted_in_none += sum(1 for r in llm_by_aid.get(aid, [])
                                          if r["predicate"] not in ("NONE", ""))

    lines = []
    def out(s):
        print(s); lines.append(s)

    out(f"# Phase C Stage 4 Evaluation: {args.llm_version} on {args.gold} split\n")
    out(f"## Overall Metrics\n")
    out(f"| Metric | Value |")
    out(f"|---|---|")
    out(f"| True Positives  | {n_tp} |")
    out(f"| False Positives | {n_fp} |")
    out(f"| False Negatives | {n_fn} |")
    out(f"| **Precision**   | **{precision:.3f}** |")
    out(f"| **Recall**      | **{recall:.3f}** |")
    out(f"| **F1**          | **{f1:.3f}** |")

    out(f"\n## T0/NONE Abstracts (LLM correctly refused to extract)\n")
    out(f"| Metric | Count |")
    out(f"|---|---|")
    out(f"| Gold abstracts marked T0/NONE        | {none_correct + none_violated} |")
    out(f"| LLM also refused to extract          | {none_correct} |")
    out(f"| LLM hallucinated triples in NONE abs | {none_violated} ({extracted_in_none} bogus triples) |")

    out(f"\n## Type Violations (predicate-type schema mismatch)\n")
    out(f"LLM produced **{len(type_violations)} triples** where predicate doesn't match subject/object types:")
    for aid, l in type_violations[:10]:
        expected = ALLOWED_PREDICATES.get(l["predicate"])
        out(f"  - {aid}: `{l['subject_type']}-[{l['predicate']}]->{l['object_type']}` (expects {expected})")
    if len(type_violations) > 10:
        out(f"  ...and {len(type_violations) - 10} more")

    out(f"\n## Per-Predicate Breakdown\n")
    out(f"| Predicate | TP | FP | FN | Precision | Recall | F1 |")
    out(f"|---|---|---|---|---|---|---|")
    for p in sorted(all_preds):
        t = pred_tp[p]; fp_p = pred_fp[p]; fn_p = pred_fn[p]
        prec = t / (t + fp_p) if (t + fp_p) > 0 else 0
        rec = t / (t + fn_p) if (t + fn_p) > 0 else 0
        f1_p = 2*prec*rec/(prec+rec) if (prec+rec) > 0 else 0
        out(f"| {p} | {t} | {fp_p} | {fn_p} | {prec:.2f} | {rec:.2f} | {f1_p:.2f} |")

    out(f"\n## Per-Stratum Breakdown\n")
    out(f"| Stratum | TP | FP | FN | Precision | Recall | F1 |")
    out(f"|---|---|---|---|---|---|---|")
    for s in sorted(all_strata):
        t = stratum_tp[s]; fp_s = stratum_fp[s]; fn_s = stratum_fn[s]
        prec = t / (t + fp_s) if (t + fp_s) > 0 else 0
        rec = t / (t + fn_s) if (t + fn_s) > 0 else 0
        f1_s = 2*prec*rec/(prec+rec) if (prec+rec) > 0 else 0
        out(f"| {s} | {t} | {fp_s} | {fn_s} | {prec:.2f} | {rec:.2f} | {f1_s:.2f} |")

    out(f"\n## Sample False Positives (LLM extracted, no gold match)\n")
    for aid, l in fp[:8]:
        out(f"  - {aid}: `{l['subject_name']}` -[{l['predicate']}]-> `{l['object_name']}`")
        out(f"     evidence: \"{l['evidence_span'][:120]}...\"")
    if len(fp) > 8:
        out(f"  ...and {len(fp) - 8} more")

    out(f"\n## Sample False Negatives (gold has, LLM missed)\n")
    for aid, g in fn[:8]:
        out(f"  - {aid}: `{g['subject_name']}` -[{g['predicate']}]-> `{g['object_name']}`")
        out(f"     evidence: \"{g['evidence_span'][:120]}...\"")
    if len(fn) > 8:
        out(f"  ...and {len(fn) - 8} more")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n--- Report saved to {report_path} ---")


if __name__ == "__main__":
    main()
