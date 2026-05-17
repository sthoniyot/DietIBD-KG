"""Prepare 100 stratified abstracts for gold-standard annotation.

Reads data/raw/pubmed/abstracts.jsonl, samples a stratified 100,
writes two files for the annotator (you):
  1. gold_standard_to_annotate.tsv - one row per abstract (read this)
  2. gold_standard_annotations.tsv - empty template (fill this)
"""
import csv
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE = PROJECT_ROOT / "data" / "raw" / "pubmed" / "abstracts.jsonl"
OUTPUT_DIR = PROJECT_ROOT / "data" / "processed"
READ_FILE = OUTPUT_DIR / "gold_standard_to_annotate.tsv"
ANNOTATE_FILE = OUTPUT_DIR / "gold_standard_annotations.tsv"

random.seed(42)  # reproducible sampling

# Load all abstracts
print("Loading abstracts...")
articles = []
with open(CACHE, encoding="utf-8") as f:
    for line in f:
        articles.append(json.loads(line))
print(f"  {len(articles):,} abstracts loaded")

# Classify each abstract by stratum based on MeSH terms + publication type
def classify(art):
    """Assign one of 6 strata."""
    mesh = set(art.get("mesh_terms", []))
    pub_types = set(art.get("publication_types", []))
    abstract_lower = art.get("abstract", "").lower()
    title_lower = art.get("title", "").lower()
    text = title_lower + " " + abstract_lower

    is_review = "Review" in pub_types or "Systematic Review" in pub_types
    has_microbiome = "Gastrointestinal Microbiome" in mesh or "microbiom" in text or "microbiota" in text
    has_ibd = "Inflammatory Bowel Diseases" in mesh or "Crohn Disease" in mesh \
              or "Colitis, Ulcerative" in mesh or "crohn" in text or "ulcerative colitis" in text
    has_diet = "Diet" in mesh or "diet" in text or "nutrition" in text or "food" in text
    has_bioactive = any(b in text for b in ["butyrate", "short-chain fatty acid", "scfa",
                                              "tryptophan", "bile acid", "indole",
                                              "polyphenol", "omega-3", "fiber"])
    has_specific_microbe = any(m in text for m in ["faecalibacterium", "akkermansia",
                                                     "roseburia", "bacteroides",
                                                     "lactobacillus", "bifidobacterium"])
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


print("\nClassifying abstracts by stratum...")
by_stratum = defaultdict(list)
for art in articles:
    by_stratum[classify(art)].append(art)
for stratum, items in by_stratum.items():
    print(f"  {stratum:<25} {len(items):>5,}")

# Stratification target per Appendix C
targets = {
    "diet_microbiome_ibd": 25,
    "microbe_ibd": 25,
    "bioactive_ibd": 20,
    "reviews": 10,
    "off_scope": 10,
    "general": 10,  # mixed-bucket fallback
}

# Sample stratified
print("\nSampling...")
selected = []
for stratum, target in targets.items():
    pool = by_stratum.get(stratum, [])
    if len(pool) < target:
        print(f"  WARN: only {len(pool)} available for {stratum}, want {target}")
        selected.extend(pool)
    else:
        sample = random.sample(pool, target)
        selected.extend(sample)
        print(f"  {stratum:<25} sampled {len(sample)}/{target}")

# Order: easier strata first to build confidence, complex strata later
order_priority = {
    "diet_microbiome_ibd": 1,
    "microbe_ibd": 2,
    "bioactive_ibd": 3,
    "off_scope": 4,
    "general": 5,
    "reviews": 6,
}

# Add classification metadata
for art in selected:
    art["_stratum"] = classify(art)

selected.sort(key=lambda a: (order_priority[a["_stratum"]], a["pmid"]))

# Write the readable file with full text
print(f"\nWriting {READ_FILE}...")
with open(READ_FILE, "w", encoding="utf-8", newline="") as f:
    writer = csv.writer(f, delimiter="\t", quoting=csv.QUOTE_ALL)
    writer.writerow([
        "annot_id", "stratum", "pmid", "year", "journal",
        "title", "abstract", "doi", "publication_types", "mesh_terms"
    ])
    for idx, art in enumerate(selected, 1):
        writer.writerow([
            f"A{idx:03d}",
            art["_stratum"],
            art["pmid"],
            art.get("year", ""),
            art.get("journal", ""),
            art.get("title", ""),
            art.get("abstract", ""),
            art.get("doi", ""),
            "|".join(art.get("publication_types", [])),
            "|".join(art.get("mesh_terms", [])[:10]),
        ])

# Write the empty annotation template
print(f"Writing {ANNOTATE_FILE}...")
with open(ANNOTATE_FILE, "w", encoding="utf-8", newline="") as f:
    writer = csv.writer(f, delimiter="\t", quoting=csv.QUOTE_ALL)
    writer.writerow([
        "annot_id", "pmid", "triple_id",
        "subject_name", "subject_type",
        "predicate",
        "object_name", "object_type",
        "evidence_span",
        "evidence_type", "your_confidence", "notes",
    ])
    # Write one example row at the top to show format
    writer.writerow([
        "EXAMPLE", "EXAMPLE",  "EX1",
        "Faecalibacterium prausnitzii", "Microbe",
        "decreased_in",
        "Crohn's disease", "IBD_Outcome",
        "F. prausnitzii abundance was reduced in CD patients (p<0.001)",
        "cohort", "0.90",
        "Sample size n=84 mentioned",
    ])

print(f"\nDone. Wrote {len(selected)} abstracts to annotate.")
print(f"  Read file:     {READ_FILE}")
print(f"  Annotate file: {ANNOTATE_FILE}")
print(f"\nNext: open these in your spreadsheet of choice.")
