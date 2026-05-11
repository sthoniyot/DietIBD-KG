"""Ingest curated FODMAP food classifications.

Source: Multi-source consensus from published FODMAP food lists:
  - Monash University FODMAP educational pages
  - Healthline FODMAP food list (2022)
  - Alberta Health Services Low FODMAP Eating
  - UVA Digestive Health Center FODMAP guide
  - IBSDiets.org FODMAP Food List
  - SelfDecode FODMAP Food List

Each food is included only when 3+ sources agree on classification.

Triple types emitted:
  (food, has_high_FODMAP_of, FODMAP_compound)  - for high-FODMAP foods
  (food, is_low_FODMAP_food, low_FODMAP)       - for low-FODMAP foods

Output: data/processed/triples_fodmap.tsv
"""
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import PROCESSED_DATA
from ingestion.triple import Triple, write_triples_tsv
from normalization.ontology_loader import load_ontology, search_ontology

FODMAP_TSV = PROCESSED_DATA / "fodmap_classifications.tsv"
OUTPUT = PROCESSED_DATA / "triples_fodmap.tsv"

# FODMAP class -> ChEBI mapping for the high-FODMAP triples
FODMAP_CLASS_TO_CHEBI = {
    "lactose": ("CHEBI:17716", "lactose"),
    "fructose": ("CHEBI:28645", "D-fructose"),
    "sorbitol": ("CHEBI:30911", "sorbitol"),
    "mannitol": ("CHEBI:16899", "D-mannitol"),
    "fructans": ("CHEBI:24482", "fructan"),
    "galacto-oligosaccharide": ("CHEBI:24151", "oligosaccharide"),
}

# For low-FODMAP classification we use a paper-specific identifier
LOW_FODMAP_OBJECT = ("FODMAP:low_FODMAP", "low FODMAP food", "Bioactive")


def main():
    print("Loading FODMAP TSV...")
    df = pd.read_csv(FODMAP_TSV, sep='\t')
    print(f"  {len(df)} food-FODMAP rows loaded")

    print("\nLoading FoodOn ontology...")
    foodon = load_ontology("foodon.owl")
    print(f"  {len(foodon):,} FoodOn terms loaded")

    triples = []
    skip_food_unmapped = 0
    skip_fodmap_unmapped = 0

    for _, row in df.iterrows():
        food_name = str(row['food_name']).strip()
        fodmap_class = str(row['fodmap_class']).strip().lower()
        content_level = str(row['content_level']).strip().lower()
        notes = str(row.get('notes', '')).strip()

        # Resolve food to FoodOn
        food_results = search_ontology(foodon, food_name, max_results=1, return_match_type=True)
        if not food_results or food_results[0][3] not in ('exact_label', 'exact_synonym'):
            skip_food_unmapped += 1
            continue
        food_id, food_label, _, _ = food_results[0]

        if content_level == 'low':
            # Low FODMAP classification
            triple = Triple(
                subject_id=food_id,
                subject_label=food_label,
                subject_type="Food",
                predicate="is_low_FODMAP_food",
                object_id=LOW_FODMAP_OBJECT[0],
                object_label=LOW_FODMAP_OBJECT[1],
                object_type=LOW_FODMAP_OBJECT[2],
                source="FODMAP_consensus",
                source_id=f"{food_name}|low",
                publication_id=None,
                evidence_type="review",
                confidence=0.90,
                sample_type=None,
                method="Multi-source consensus from 5+ published FODMAP food lists",
                notes=notes if notes != '-' else None,
            )
            triples.append(triple)

        elif content_level == 'high':
            # High FODMAP - need ChEBI mapping for FODMAP class
            if fodmap_class not in FODMAP_CLASS_TO_CHEBI:
                print(f"  WARN: unknown FODMAP class '{fodmap_class}' for {food_name}")
                skip_fodmap_unmapped += 1
                continue
            chebi_id, chebi_label = FODMAP_CLASS_TO_CHEBI[fodmap_class]
            triple = Triple(
                subject_id=food_id,
                subject_label=food_label,
                subject_type="Food",
                predicate="has_high_FODMAP_content_of",
                object_id=chebi_id,
                object_label=chebi_label,
                object_type="Bioactive",
                source="FODMAP_consensus",
                source_id=f"{food_name}|{fodmap_class}",
                publication_id=None,
                evidence_type="review",
                confidence=0.90,
                sample_type=None,
                method="Multi-source consensus from 5+ published FODMAP food lists",
                notes=notes if notes != '-' else None,
            )
            triples.append(triple)

    print(f"\nIngestion summary:")
    print(f"  Triples emitted:          {len(triples)}")
    print(f"  Skipped (food unmapped):  {skip_food_unmapped}")
    print(f"  Skipped (FODMAP unmapped):{skip_fodmap_unmapped}")

    if triples:
        from collections import Counter
        print(f"\nPredicate distribution:")
        for p, count in Counter(t.predicate for t in triples).most_common():
            print(f"  {p}: {count}")
        print(f"\nFODMAP class distribution (high-FODMAP triples):")
        high = [t for t in triples if t.predicate == "has_high_FODMAP_content_of"]
        for cls, count in Counter(t.object_label for t in high).most_common():
            print(f"  {cls}: {count}")
        write_triples_tsv(triples, OUTPUT)
        print(f"\nWrote {len(triples)} triples to {OUTPUT}")
        print(f"  File size: {OUTPUT.stat().st_size / 1024:.1f} KB")

        # Sample
        print(f"\nSample triples:")
        for t in triples[:5]:
            print(f"  {t.subject_label} --[{t.predicate}]--> {t.object_label}")
        for t in [t for t in triples if t.predicate == "is_low_FODMAP_food"][:5]:
            print(f"  {t.subject_label} --[{t.predicate}]--> {t.object_label}")


if __name__ == "__main__":
    main()
