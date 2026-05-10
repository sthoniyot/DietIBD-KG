"""Ingest Disbiome microbe-disease associations for IBD.

Reads:    data/raw/disbiome/disbiome_export.json (10,866 entries)
Filters:  IBD-related diseases (Crohn's, UC, IBD, Inactive CD), Human host
Outputs:  data/processed/triples_disbiome.tsv (~750 triples)

Disbiome already provides organism_ncbi_id with 98.4% coverage. For the few
entries without it, we fall back to NCBI Taxonomy cascaded search.

Disease names are mapped to Disease Ontology IDs.
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import RAW_DATA, PROCESSED_DATA
from ingestion.triple import Triple, write_triples_tsv
from normalization.ncbi_taxonomy import load_cache, search_microbe

# IBD disease name -> DOID ID mapping.
# Source: Disease Ontology (already validated in our cache).
IBD_DISEASE_MAP = {
    "Crohn's Disease":              ("DOID:8778",     "Crohn's disease",              "IBD_Outcome"),
    "Ulcerative Colitis":           ("DOID:8577",     "ulcerative colitis",           "IBD_Outcome"),
    "Inflammatory Bowel Disease":   ("DOID:0050589",  "inflammatory bowel disease",   "IBD_Outcome"),
    "Inactive Crohn's Disease":     ("DOID:8778",     "Crohn's disease (inactive)",   "IBD_Outcome"),
}

# Disbiome qualitative_outcome -> KG predicate
PREDICATE_MAP = {
    "Reduced":  "decreased_in",
    "Elevated": "increased_in",
}


def normalize_microbe(entry, ncbi_cache):
    """Resolve organism to NCBI Taxonomy ID.

    Strategy:
      1. Use entry's organism_ncbi_id if present (98.4% of Disbiome IBD entries)
      2. Fall back to cascaded search by organism_name
      3. Return None if both fail
    """
    organism_name = entry.get("organism_name", "").strip()
    if not organism_name:
        return None

    ncbi_id = entry.get("organism_ncbi_id")
    if ncbi_id:
        return f"NCBITaxon:{ncbi_id}", organism_name

    # Fallback: cascaded search
    results = search_microbe(organism_name, ncbi_cache, max_results=1)
    if results:
        tax_id, canonical, _, match_type = results[0]
        return f"NCBITaxon:{tax_id}", canonical

    return None


def compute_confidence(entry):
    """Score from 0.0 to 1.0 based on Disbiome metadata.

    Baseline 0.85 (curated source).
    +0.03 if quantitative ratio is reported
    -0.05 if method is uncommon (DGGE, qPCR rather than 16S/shotgun)
    """
    confidence = 0.85
    if entry.get("ratio"):
        confidence += 0.03
    method = (entry.get("method_name") or "").lower()
    if "16s" in method or "metagenomic" in method or "shotgun" in method:
        pass  # baseline
    elif "qpcr" in method or "dgge" in method:
        confidence -= 0.05
    return round(min(max(confidence, 0.5), 0.95), 2)


def ingest():
    """Main ingestion driver."""
    input_path = RAW_DATA / "disbiome" / "disbiome_export.json"
    output_path = PROCESSED_DATA / "triples_disbiome.tsv"

    print(f"Reading {input_path}...")
    with open(input_path) as f:
        data = json.load(f)
    print(f"  Loaded {len(data):,} total entries")

    print("Loading NCBI Taxonomy cache (for fallback lookups)...")
    ncbi_cache = load_cache()
    print(f"  {len(ncbi_cache['tax_to_names']):,} taxa available\n")

    # Filter to IBD entries with mappable disease names
    print("Filtering and normalizing...")
    triples = []
    skip_no_disease = 0
    skip_no_microbe = 0
    skip_no_predicate = 0
    fallback_used = 0

    for entry in data:
        # Disease filter and normalization
        disease_name = entry.get("disease_name", "")
        if disease_name not in IBD_DISEASE_MAP:
            continue  # Not IBD or variant we don't handle

        disease_id, disease_label, disease_type = IBD_DISEASE_MAP[disease_name]

        # Predicate
        outcome = entry.get("qualitative_outcome", "")
        if outcome not in PREDICATE_MAP:
            skip_no_predicate += 1
            continue
        predicate = PREDICATE_MAP[outcome]

        # Microbe normalization
        microbe_result = normalize_microbe(entry, ncbi_cache)
        if microbe_result is None:
            skip_no_microbe += 1
            continue
        microbe_id, microbe_label = microbe_result

        # Track if we used the fallback
        if not entry.get("organism_ncbi_id"):
            fallback_used += 1

        # Build the triple
        triple = Triple(
            subject_id=microbe_id,
            subject_label=microbe_label,
            subject_type="Microbe",
            predicate=predicate,
            object_id=disease_id,
            object_label=disease_label,
            object_type=disease_type,
            source="Disbiome",
            source_id=str(entry.get("experiment_id", "")),
            publication_id=str(entry.get("publication_id", "")) if entry.get("publication_id") else None,
            evidence_type="observational",
            confidence=compute_confidence(entry),
            sample_type=entry.get("sample_name") or None,
            method=entry.get("method_name") or None,
            notes=f"Inactive form" if "Inactive" in disease_name else None,
        )
        triples.append(triple)

    print(f"\nIngestion summary:")
    print(f"  Triples produced:        {len(triples):,}")
    print(f"  NCBI fallback used:      {fallback_used} entries")
    print(f"  Skipped (no microbe):    {skip_no_microbe}")
    print(f"  Skipped (no predicate):  {skip_no_predicate}")

    # Predicate distribution
    print(f"\nPredicate distribution:")
    pred_counts = Counter(t.predicate for t in triples)
    for pred, count in pred_counts.most_common():
        print(f"  {pred:<20} {count:>4}")

    # Disease distribution
    print(f"\nDisease distribution:")
    disease_counts = Counter(t.object_label for t in triples)
    for d, count in disease_counts.most_common():
        print(f"  {d:<35} {count:>4}")

    # Top microbes
    print(f"\nTop 10 microbes:")
    microbe_counts = Counter(t.subject_label for t in triples)
    for m, count in microbe_counts.most_common(10):
        print(f"  ({count:>3}) {m}")

    # Confidence distribution
    print(f"\nConfidence distribution:")
    conf_buckets = Counter()
    for t in triples:
        bucket = f"{t.confidence:.2f}"
        conf_buckets[bucket] += 1
    for c in sorted(conf_buckets.keys()):
        print(f"  {c:<6} {conf_buckets[c]:>4}")

    # Write output
    write_triples_tsv(triples, output_path)
    print(f"\nWrote {len(triples):,} triples to {output_path}")
    print(f"  File size: {output_path.stat().st_size / 1024:.1f} KB")

    # Sanity check: Faecalibacterium prausnitzii decreased_in Crohn's disease
    print(f"\n=== Sanity check: F. prausnitzii in Crohn's disease ===")
    fp_cd = [t for t in triples
             if t.subject_label == "Faecalibacterium prausnitzii"
             and "Crohn" in t.object_label]
    if fp_cd:
        print(f"  Found {len(fp_cd)} F. prausnitzii x Crohn's triples:")
        decreased = sum(1 for t in fp_cd if t.predicate == "decreased_in")
        increased = sum(1 for t in fp_cd if t.predicate == "increased_in")
        print(f"    decreased_in: {decreased}")
        print(f"    increased_in: {increased}")
        if decreased > increased:
            print(f"  + Reproduces canonical IBD finding (F. prausnitzii depleted in CD)")
        else:
            print(f"  ! Unexpected: F. prausnitzii not predominantly decreased in CD")
    else:
        print("  No F. prausnitzii x Crohn's triples found (unexpected)")


if __name__ == "__main__":
    ingest()
