"""Merge re-annotated 19 abstracts with existing filtered 68-abstract gold standard."""
import csv
from pathlib import Path

PROCESSED = Path("data/processed")
FILTERED = PROCESSED / "gold_standard_annotations_filtered.tsv"
REANNOTATED = PROCESSED / "reannotated_19_abstracts.tsv"
OUTPUT = PROCESSED / "gold_standard_annotations_merged.tsv"

# Load both files
with open(FILTERED, encoding="utf-8") as f:
    filtered_rows = list(csv.DictReader(f, delimiter="\t"))
    fieldnames = filtered_rows[0].keys() if filtered_rows else None

with open(REANNOTATED, encoding="utf-8") as f:
    reannotated_rows = list(csv.DictReader(f, delimiter="\t"))

# Check for annot_id conflicts (there should be none since filter excluded these)
filtered_aids = set(r["annot_id"] for r in filtered_rows)
reannotated_aids = set(r["annot_id"] for r in reannotated_rows)
overlap = filtered_aids & reannotated_aids
if overlap:
    print(f"WARNING: Overlapping annot_ids will use re-annotated version: {sorted(overlap)}")

# Merge: keep all filtered rows + all re-annotated rows
# (For any overlap, the re-annotated takes precedence by removing the filtered ones)
merged = [r for r in filtered_rows if r["annot_id"] not in reannotated_aids]
merged.extend(reannotated_rows)

# Sort by annot_id then triple_id
merged.sort(key=lambda r: (r["annot_id"], r.get("triple_id", "")))

# Write
with open(OUTPUT, "w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(fieldnames), delimiter="\t",
                            quoting=csv.QUOTE_MINIMAL)
    writer.writeheader()
    for r in merged:
        clean = {c: (r.get(c) or "") for c in fieldnames}
        writer.writerow(clean)

# Summary
unique_aids = sorted(set(r["annot_id"] for r in merged))
real = [r for r in merged if r["predicate"] != "NONE"]
none_r = [r for r in merged if r["predicate"] == "NONE"]

print(f"=== Merge complete ===")
print(f"Filtered rows:       {len(filtered_rows)} ({len(filtered_aids)} abstracts)")
print(f"Re-annotated rows:   {len(reannotated_rows)} ({len(reannotated_aids)} abstracts)")
print(f"Merged total:        {len(merged)} rows")
print(f"Unique abstracts:    {len(unique_aids)}")
print(f"Real triples:        {len(real)}")
print(f"T0/NONE rows:        {len(none_r)}")
print(f"\nOutput: {OUTPUT}")
