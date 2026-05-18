"""Filter gold_standard_annotations.tsv to only include annotations where
PMID matches between annotations file and gold_standard_to_annotate.tsv.

This is the Stage 4 data hygiene step after discovering PMID mismatch
issues from multi-iteration file editing.
"""
import csv
from pathlib import Path

PROCESSED = Path("data/processed")
ANNOTATIONS = PROCESSED / "gold_standard_annotations.tsv"
SOURCE = PROCESSED / "gold_standard_to_annotate.tsv"
FILTERED = PROCESSED / "gold_standard_annotations_filtered.tsv"

# Load source PMIDs
with open(SOURCE, encoding="utf-8") as f:
    source_pmids = {r["annot_id"]: r["pmid"] for r in csv.DictReader(f, delimiter="\t")}

# Load and filter annotations
with open(ANNOTATIONS, encoding="utf-8") as f:
    reader = csv.DictReader(f, delimiter="\t")
    fieldnames = reader.fieldnames
    all_rows = list(reader)

# Identify annot_ids to keep (PMID matches source)
kept_aids = set()
dropped_aids = set()
for r in all_rows:
    aid = r["annot_id"]
    if aid not in source_pmids:
        dropped_aids.add(aid)
        continue
    if r["pmid"] == source_pmids[aid]:
        kept_aids.add(aid)
    else:
        dropped_aids.add(aid)

kept_rows = [r for r in all_rows if r["annot_id"] in kept_aids]

print(f"Total rows in original:       {len(all_rows)}")
print(f"Unique annot_ids original:    {len(set(r['annot_id'] for r in all_rows))}")
print(f"Unique annot_ids KEPT:        {len(kept_aids)} (PMID matches source)")
print(f"Unique annot_ids DROPPED:     {len(dropped_aids)} (PMID mismatch)")
print(f"Rows kept:                    {len(kept_rows)}")
print(f"\nDropped annot_ids: {sorted(dropped_aids)}")

# Stratum coverage check on what's kept
with open(SOURCE, encoding="utf-8") as f:
    source_full = {r["annot_id"]: r for r in csv.DictReader(f, delimiter="\t")}
from collections import Counter
kept_strata = Counter(source_full[aid]["stratum"] for aid in kept_aids if aid in source_full)
total_strata = Counter(r["stratum"] for r in source_full.values())
print(f"\nStratum coverage in filtered set:")
for s in sorted(total_strata):
    print(f"  {s:<25} {kept_strata.get(s, 0):>2}/{total_strata[s]}")

# Write filtered file
with open(FILTERED, "w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t",
                            quoting=csv.QUOTE_MINIMAL)
    writer.writeheader()
    for r in kept_rows:
        writer.writerow(r)
print(f"\nWritten to: {FILTERED}")
print(f"\nNext step:")
print(f"  mv {ANNOTATIONS} {ANNOTATIONS}.original")
print(f"  mv {FILTERED} {ANNOTATIONS}")
print(f"  python scripts/split_gold_standard.py")
