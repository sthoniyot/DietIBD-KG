"""Ingest FooDB food-bioactive compound associations for IBD-relevant compounds.

Uses pre-built ChEBI mapping from scripts/build_foodb_chebi_map.py.

Pipeline:
1. Load pre-built FooDB compound_id -> ChEBI ID mapping (2,410 verified)
2. Load Food.csv, resolve each food to FoodOn ID via cascaded matcher
3. Stream Content.csv in chunks, emit (food, contains, compound) triples
4. Write to data/processed/triples_foodb.tsv

Reads:
    data/processed/foodb_chebi_mapping.tsv (pre-built ChEBI mapping)
    data/raw/foodb/foodb_2020_04_07_csv/{Compound,Food,Content}.csv

Outputs:
    data/processed/triples_foodb.tsv
"""
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import RAW_DATA, PROCESSED_DATA
from ingestion.triple import Triple, write_triples_tsv
from normalization.ontology_loader import load_ontology, search_ontology

FOODB_DIR = RAW_DATA / "foodb" / "foodb_2020_04_07_csv"
CHEBI_MAPPING = PROCESSED_DATA / "foodb_chebi_mapping.tsv"
ALLOWLIST = PROCESSED_DATA / "foodb_compound_allowlist.tsv"
OUTPUT = PROCESSED_DATA / "triples_foodb.tsv"

ALLOWLIST_COMPOUND_IDS = {
    30807, 3293, 12295, 31375, 11907, 633, 2571, 17707, 12611, 31083,
    2250, 446, 12663, 14542, 11831, 2608, 698, 3103, 12465, 11875,
    12861, 1141, 5763, 23325, 1182, 18710, 661, 12323, 12531, 1145,
    1982, 1134, 371, 9021, 710, 11947, 10415, 12599,
}


def step(msg):
    print(f"\n=== {msg} ===  [{time.strftime('%H:%M:%S')}]", flush=True)


def load_compound_to_chebi():
    """Load the pre-built compound_id -> {chebi_id, chebi_label, foodb_name} mapping."""
    step("Step 1: Load compound -> ChEBI mapping")
    if not CHEBI_MAPPING.exists():
        raise FileNotFoundError(
            f"ChEBI mapping not found at {CHEBI_MAPPING}. "
            f"Run scripts/build_foodb_chebi_map.py first."
        )
    df = pd.read_csv(CHEBI_MAPPING, sep='\t')
    mapping = {}
    for _, row in df.iterrows():
        mapping[row['foodb_compound_id']] = {
            'chebi_id': row['chebi_id'],
            'chebi_label': row['chebi_label'],
            'foodb_name': row['foodb_compound_name'],
            'allowlisted': row['foodb_compound_id'] in ALLOWLIST_COMPOUND_IDS,
            'match_source': row['match_source'],
        }
    n_allow = sum(1 for v in mapping.values() if v['allowlisted'])
    print(f"  {len(mapping):,} compounds mapped to ChEBI")
    print(f"  Of those, {n_allow} are from the IBD allow-list")
    return mapping


def build_food_mapping():
    """Resolve each FooDB food to FoodOn ID."""
    step("Step 2: Build food -> FoodOn mapping")
    food_df = pd.read_csv(FOODB_DIR / "Food.csv", encoding='utf-8', on_bad_lines='skip')
    print(f"  {len(food_df)} foods loaded")

    foodon = load_ontology("foodon.owl")
    food_map = {}
    matched, skipped = 0, 0

    for _, row in food_df.iterrows():
        food_id = row['id']
        name = str(row['name']).strip() if pd.notna(row['name']) else ''
        if not name:
            skipped += 1
            continue
        results = search_ontology(foodon, name, max_results=1, return_match_type=True)
        if results and results[0][3] in ('exact_label', 'exact_synonym'):
            foodon_id, foodon_label, _, match_type = results[0]
            food_map[food_id] = {
                'name': name,
                'foodon_id': foodon_id,
                'foodon_label': foodon_label,
                'match_type': match_type,
            }
            matched += 1
        else:
            skipped += 1

    print(f"  Foods mapped:  {matched}")
    print(f"  Foods skipped: {skipped}")
    return food_map


def ingest_content(compound_chebi_map, food_map):
    step("Step 3: Stream Content.csv and emit triples")
    print("Processing 5.1M rows in chunks (~3-5 min)")

    triples = []
    n_processed = 0
    n_emitted = 0
    skip_not_compound = 0
    skip_not_in_subset = 0
    skip_no_food = 0
    skip_no_content = 0

    chunks = pd.read_csv(
        FOODB_DIR / "Content.csv",
        encoding='utf-8',
        engine='python',
        on_bad_lines='skip',
        usecols=['source_id', 'source_type', 'food_id', 'standard_content',
                 'orig_content', 'orig_unit', 'citation', 'citation_type'],
        chunksize=200000,
    )

    for chunk_idx, chunk in enumerate(chunks):
        n_processed += len(chunk)

        compound_rows = chunk[chunk['source_type'] == 'Compound']
        skip_not_compound += len(chunk) - len(compound_rows)

        in_subset = compound_rows[compound_rows['source_id'].isin(compound_chebi_map)]
        skip_not_in_subset += len(compound_rows) - len(in_subset)

        for _, row in in_subset.iterrows():
            compound_id = row['source_id']
            food_id = row['food_id']

            food_info = food_map.get(food_id)
            if not food_info:
                skip_no_food += 1
                continue

            # Determine evidence quality:
            #   - Has measurable concentration (>0): strong presence, high confidence
            #   - Has zero concentration: below detection limit, drop as not-meaningful
            #   - No concentration data at all (NaN): presence-only, lower confidence
            sc = row['standard_content']
            oc = row['orig_content']

            if pd.notna(sc) and sc == 0:
                skip_no_content += 1
                continue
            if pd.notna(oc) and oc == 0 and pd.isna(sc):
                skip_no_content += 1
                continue

            has_concentration = (pd.notna(sc) and sc > 0) or (pd.notna(oc) and oc > 0)
            presence_only = not has_concentration  # row exists, no concentration

            compound_info = compound_chebi_map[compound_id]

            # Confidence scoring
            confidence = 0.80
            if compound_info['allowlisted']:
                confidence += 0.05
            if has_concentration:
                confidence += 0.05
            else:
                confidence -= 0.10  # Presence-only is less certain
            confidence = round(min(max(confidence, 0.5), 0.95), 2)

            citation_str = None
            if pd.notna(row['citation']) and pd.notna(row['citation_type']):
                citation_str = f"{row['citation_type']}: {row['citation']}"
            if presence_only:
                citation_str = (citation_str + " | presence_only") if citation_str else "presence_only"

            triple = Triple(
                subject_id=food_info['foodon_id'],
                subject_label=food_info['foodon_label'],
                subject_type="Food",
                predicate="contains",
                object_id=compound_info['chebi_id'],
                object_label=compound_info['chebi_label'],
                object_type="Bioactive",
                source="FooDB",
                source_id=str(compound_id),
                publication_id=None,
                evidence_type="observational",
                confidence=confidence,
                sample_type=None,
                method=None,
                notes=citation_str,
            )
            triples.append(triple)
            n_emitted += 1

        if (chunk_idx + 1) % 5 == 0:
            print(f"  Progress: {n_processed:,}/5,145,533 ({100*n_processed/5145533:.0f}%) "
                  f"-> {n_emitted:,} triples")

    print(f"\nIngestion summary:")
    print(f"  Rows processed:              {n_processed:,}")
    print(f"  Skipped (not Compound type): {skip_not_compound:,}")
    print(f"  Skipped (not in subset):     {skip_not_in_subset:,}")
    print(f"  Skipped (food unmapped):     {skip_no_food:,}")
    print(f"  Skipped (no content):        {skip_no_content:,}")
    print(f"  Triples emitted:             {n_emitted:,}")
    return triples


def main():
    overall_start = time.time()

    compound_chebi = load_compound_to_chebi()
    food_map = build_food_mapping()
    triples = ingest_content(compound_chebi, food_map)

    step("Step 4: Write output and statistics")
    if not triples:
        print("WARNING: zero triples produced.")
        return

    write_triples_tsv(triples, OUTPUT)
    print(f"Wrote {len(triples):,} triples to {OUTPUT}")
    print(f"  File size: {OUTPUT.stat().st_size / 1024 / 1024:.1f} MB")

    print("\nTop 15 foods:")
    for food, count in Counter(t.subject_label for t in triples).most_common(15):
        print(f"  ({count:>5}) {food}")

    print("\nTop 15 compounds:")
    for c, count in Counter(t.object_label for t in triples).most_common(15):
        print(f"  ({count:>5}) {c}")

    print("\nSanity checks (well-known triples):")
    by_label = {}
    for t in triples:
        by_label.setdefault((t.subject_label, t.object_label), []).append(t)

    checks = [
        ("salmon", "all-cis-5,8,11,14,17-icosapentaenoic acid"),  # ChEBI canonical label
        ("blueberry", "quercetin"),
    ]
    for food_pat, compound_pat in checks:
        found = [(s, c) for (s, c) in by_label.keys()
                 if food_pat.lower() in str(s).lower() and compound_pat.lower() in str(c).lower()]
        if found:
            print(f"  + Found: {found[0]}")
        else:
            print(f"  ? Not found: '{food_pat}' x '{compound_pat}'")

    print("\nConfidence distribution:")
    for c in sorted(Counter(f"{t.confidence:.2f}" for t in triples).items()):
        print(f"  {c[0]}: {c[1]}")

    elapsed = time.time() - overall_start
    print(f"\nTotal runtime: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
