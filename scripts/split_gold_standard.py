"""Stratified 80/20 dev/test split of the gold-standard annotations.

Splits the 87 annotated abstracts into:
  - 70 dev abstracts (for prompt iteration)
  - 17 test abstracts (held out for final evaluation)

Stratified by the source stratum (diet_microbiome_ibd, microbe_ibd, etc.)
so both splits proportionally represent the corpus.

Also designates 5 dev abstracts as "few-shot examples" - these are excluded
from the evaluation set to avoid double-counting (we show the LLM these
examples, so it should get them right by definition).

Random seed = 42 for reproducibility.

Outputs:
  data/processed/gold_split_dev.tsv      - 65 dev abstracts (eval pool)
  data/processed/gold_split_fewshot.tsv  - 5 abstracts used as prompt examples
  data/processed/gold_split_test.tsv     - 17 held-out test abstracts
"""
import csv
import random
from collections import defaultdict
from pathlib import Path

random.seed(42)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ANNOTATIONS = PROJECT_ROOT / "data" / "processed" / "gold_standard_annotations.tsv"
TO_ANNOTATE = PROJECT_ROOT / "data" / "processed" / "gold_standard_to_annotate.tsv"
OUT_DIR = PROJECT_ROOT / "data" / "processed"

# Load annotations + map to strata
print("Loading annotations and source metadata...")
with open(ANNOTATIONS, encoding="utf-8") as f:
    annot_rows = list(csv.DictReader(f, delimiter="\t"))

with open(TO_ANNOTATE, encoding="utf-8") as f:
    source = {r["annot_id"]: r for r in csv.DictReader(f, delimiter="\t")}

# Unique annotated abstracts
annotated_ids = sorted(set(r["annot_id"] for r in annot_rows))
print(f"  {len(annotated_ids)} unique annotated abstracts")

# Group by stratum
by_stratum = defaultdict(list)
for aid in annotated_ids:
    stratum = source.get(aid, {}).get("stratum", "unknown")
    by_stratum[stratum].append(aid)

print(f"\n  Stratum distribution:")
for stratum in sorted(by_stratum):
    print(f"    {stratum:<25} {len(by_stratum[stratum]):>3}")

# Stratified 80/20 dev/test
dev = []
test = []
for stratum, ids in by_stratum.items():
    shuffled = sorted(ids)  # deterministic
    random.shuffle(shuffled)
    n_test = max(1, round(len(shuffled) * 0.20))  # at least 1 per stratum
    test.extend(shuffled[:n_test])
    dev.extend(shuffled[n_test:])

print(f"\n  Initial dev/test split:")
print(f"    Dev:  {len(dev)} abstracts")
print(f"    Test: {len(test)} abstracts")

# Pick 5 few-shot examples from DEV - one per stratum where possible
# Prefer abstracts with multiple real triples (richer examples)
dev_with_triples = defaultdict(list)  # stratum -> [(annot_id, n_triples)]
for aid in dev:
    n_real = sum(1 for r in annot_rows
                 if r["annot_id"] == aid and r["predicate"] != "NONE")
    if n_real >= 2:  # prefer abstracts with 2+ real triples
        stratum = source.get(aid, {}).get("stratum", "unknown")
        dev_with_triples[stratum].append((aid, n_real))

# Pick top examples per stratum (most triples first), at most 5 total
fewshot = []
# Priority strata for examples
priority_strata = ["diet_microbiome_ibd", "microbe_ibd", "bioactive_ibd",
                   "reviews", "off_scope"]
for stratum in priority_strata:
    candidates = sorted(dev_with_triples.get(stratum, []),
                        key=lambda x: -x[1])  # most triples first
    for aid, _ in candidates:
        if aid not in fewshot:
            fewshot.append(aid)
            break
    if len(fewshot) == 5:
        break

# If we didn't get 5, fill from remaining dev abstracts
remaining_dev = [aid for aid in dev if aid not in fewshot]
while len(fewshot) < 5 and remaining_dev:
    aid = remaining_dev.pop(0)
    fewshot.append(aid)

# Remove fewshot from eval-dev set
dev_eval = [aid for aid in dev if aid not in fewshot]

print(f"\n  Final split:")
print(f"    Few-shot examples: {len(fewshot)} ({', '.join(sorted(fewshot))})")
print(f"    Dev eval set:      {len(dev_eval)}")
print(f"    Test:              {len(test)}")
print(f"    Total accounted:   {len(fewshot) + len(dev_eval) + len(test)}")

# Verify stratification balance
print(f"\n  Stratification check:")
def stratum_dist(ids):
    return {s: sum(1 for a in ids if source.get(a, {}).get("stratum") == s)
            for s in sorted(by_stratum)}

dev_dist = stratum_dist(dev_eval)
test_dist = stratum_dist(test)
fewshot_dist = stratum_dist(fewshot)

print(f"    {'Stratum':<25} {'Dev':>4} {'Test':>4} {'FewShot':>8}")
for stratum in sorted(by_stratum):
    print(f"    {stratum:<25} {dev_dist.get(stratum, 0):>4} "
          f"{test_dist.get(stratum, 0):>4} {fewshot_dist.get(stratum, 0):>8}")

# Write the splits as separate TSV files
def write_split(filepath, ids):
    """Write all annotation rows for the given abstract IDs."""
    rows_to_write = [r for r in annot_rows if r["annot_id"] in ids]
    with open(filepath, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=annot_rows[0].keys(),
                                delimiter="\t", quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for r in rows_to_write:
            writer.writerow(r)
    return len(rows_to_write)

n_dev = write_split(OUT_DIR / "gold_split_dev.tsv", dev_eval)
n_fewshot = write_split(OUT_DIR / "gold_split_fewshot.tsv", fewshot)
n_test = write_split(OUT_DIR / "gold_split_test.tsv", test)

print(f"\n  Files written:")
print(f"    gold_split_dev.tsv:     {n_dev:>3} rows ({len(dev_eval)} abstracts)")
print(f"    gold_split_fewshot.tsv: {n_fewshot:>3} rows ({len(fewshot)} abstracts)")
print(f"    gold_split_test.tsv:    {n_test:>3} rows ({len(test)} abstracts)")
