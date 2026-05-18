"""Fix gold_standard_to_annotate.tsv PMID alignment.

The to-annotate file's annot_id -> PMID mapping diverged from the gold
annotations file during multi-iteration editing. This script rebuilds
to-annotate.tsv so each annot_id has the correct PMID + matching abstract.

For each annot_id in gold_standard_annotations.tsv:
  - Look up the PMID from the annotation row
  - Look up that PMID's abstract content in data/raw/pubmed/abstracts.jsonl
  - Reconstruct the to-annotate row (annot_id, stratum, pmid, year, journal,
    title, abstract, doi, publication_types, mesh_terms)

For annot_ids in to-annotate but NOT in annotations: keep original row (these
were never annotated, so their PMID assignment doesn't matter for evaluation).

Stratum is recomputed by classifying the (corrected) abstract.
"""
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED = PROJECT_ROOT / "data" / "processed"

ANNOTATIONS = PROCESSED / "gold_standard_annotations.tsv"
SOURCE_OLD = PROCESSED / "gold_standard_to_annotate.tsv"
SOURCE_NEW = PROCESSED / "gold_standard_to_annotate.tsv.fixed"
ABSTRACTS = PROJECT_ROOT / "data" / "raw" / "pubmed" / "abstracts.jsonl"


def classify(art):
    """Re-classify into stratum (same logic as prepare_gold_standard.py)."""
    mesh = set(art.get("mesh_terms", []))
    pub_types = set(art.get("publication_types", []))
    text = (art.get("title", "") + " " + art.get("abstract", "")).lower()

    is_review = "Review" in pub_types or "Systematic Review" in pub_types
    has_microbiome = ("Gastrointestinal Microbiome" in mesh or
                      "microbiom" in text or "microbiota" in text)
    has_ibd = ("Inflammatory Bowel Diseases" in mesh or
               "Crohn Disease" in mesh or "Colitis, Ulcerative" in mesh or
               "crohn" in text or "ulcerative colitis" in text)
    has_diet = ("Diet" in mesh or "diet" in text or "nutrition" in text or
                "food" in text)
    has_bioactive = any(b in text for b in [
        "butyrate", "short-chain fatty acid", "scfa", "tryptophan",
        "bile acid", "indole", "polyphenol", "omega-3", "fiber"
    ])
    has_specific_microbe = any(m in text for m in [
        "faecalibacterium", "akkermansia", "roseburia", "bacteroides",
        "lactobacillus", "bifidobacterium"
    ])
    is_off_scope = not (has_microbiome or has_bioactive or has_specific_microbe)

    if is_review:
        return "reviews"
    if is_off_scope and has_ibd:
        return "off_scope"
    if has_diet and has_microbiome and has_ibd:
        return "diet_microbiome_ibd"
    if has_specific_microbe and has_ibd:
        return "microbe_ibd"
    if has_bioactive and has_ibd:
        return "bioactive_ibd"
    return "general"


# --- Load gold annotations: get annot_id -> pmid ---
print("Loading gold annotations...")
gold_annot_pmids = {}
with open(ANNOTATIONS, encoding="utf-8") as f:
    for r in csv.DictReader(f, delimiter="\t"):
        if r["annot_id"] not in gold_annot_pmids:
            gold_annot_pmids[r["annot_id"]] = r["pmid"]
print(f"  {len(gold_annot_pmids)} unique annot_ids in gold annotations")

# --- Load all PubMed abstracts indexed by PMID ---
print("Loading PubMed abstracts corpus...")
abstracts_by_pmid = {}
with open(ABSTRACTS, encoding="utf-8") as f:
    for line in f:
        try:
            art = json.loads(line)
            abstracts_by_pmid[art["pmid"]] = art
        except json.JSONDecodeError:
            continue
print(f"  {len(abstracts_by_pmid)} abstracts loaded")

# --- Load existing to-annotate file ---
print("Loading existing to-annotate file...")
existing = {}
with open(SOURCE_OLD, encoding="utf-8") as f:
    reader = csv.DictReader(f, delimiter="\t")
    fieldnames = reader.fieldnames
    for r in reader:
        existing[r["annot_id"]] = r
print(f"  {len(existing)} annot_ids in existing file")

# --- Build the fixed file ---
print("\nReconciling annot_id -> PMID mapping...")
fixed_rows = []
missing_in_corpus = []
mismatched_fixed = 0
unchanged = 0

# Process each annot_id present in existing file, in order
for aid in sorted(existing.keys()):
    if aid not in gold_annot_pmids:
        # Annot_id not in gold annotations - leave row as-is
        fixed_rows.append(existing[aid])
        unchanged += 1
        continue

    gold_pmid = gold_annot_pmids[aid]
    existing_pmid = existing[aid]["pmid"]

    if gold_pmid == existing_pmid:
        # Already correct - keep as-is
        fixed_rows.append(existing[aid])
        unchanged += 1
        continue

    # Mismatch - rebuild row from abstracts corpus
    if gold_pmid not in abstracts_by_pmid:
        # PMID isn't in our corpus - can't rebuild, flag this
        missing_in_corpus.append((aid, gold_pmid))
        fixed_rows.append(existing[aid])  # keep old (broken) row
        continue

    art = abstracts_by_pmid[gold_pmid]
    new_row = {
        "annot_id": aid,
        "stratum": classify(art),
        "pmid": gold_pmid,
        "year": art.get("year", ""),
        "journal": art.get("journal", ""),
        "title": art.get("title", ""),
        "abstract": art.get("abstract", ""),
        "doi": art.get("doi", ""),
        "publication_types": "|".join(art.get("publication_types", [])),
        "mesh_terms": "|".join(art.get("mesh_terms", [])[:10]),
    }
    fixed_rows.append(new_row)
    mismatched_fixed += 1

print(f"  Unchanged rows:                  {unchanged}")
print(f"  Mismatches fixed from corpus:    {mismatched_fixed}")
print(f"  PMIDs missing from corpus:       {len(missing_in_corpus)}")
if missing_in_corpus:
    print("    These need manual intervention:")
    for aid, pmid in missing_in_corpus:
        print(f"      {aid}: PMID {pmid}")

# --- Write fixed file ---
print(f"\nWriting fixed file to: {SOURCE_NEW}")
with open(SOURCE_NEW, "w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t",
                            quoting=csv.QUOTE_MINIMAL)
    writer.writeheader()
    for r in fixed_rows:
        clean = {c: (r.get(c) or "") for c in fieldnames}
        writer.writerow(clean)

print(f"\nWrote {len(fixed_rows)} rows to {SOURCE_NEW}")
print(f"\nVerify with diff, then replace:")
print(f"  diff -u {SOURCE_OLD.name} {SOURCE_NEW.name}")
print(f"  mv {SOURCE_NEW} {SOURCE_OLD}")
