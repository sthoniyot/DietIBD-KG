"""Ingest Bolte et al. 2021 diet-microbiome-marker associations.

Source: Bolte LA et al. (2021) "Long-term dietary patterns are associated with
        pro-inflammatory and anti-inflammatory features of the gut microbiome"
        Gut 70: 1287-1298. DOI: 10.1136/gutjnl-2020-322670

This is the most valuable single ingestion for DietIBD-KG because:
- 1,425 individuals (HC + CD + UC + IBS) with paired diet+microbiome data
- Statistical meta-analysis across 4 cohorts (not single-study claims)
- Includes calprotectin (S5) - direct IBD biomarker linkage
- Granular individual-food associations (S7, ~28,000 raw associations)

Sheets ingested:
    S4: Food cluster -> bacterial cluster (725 rows)
    S5: Food cluster -> inflammatory marker (50 rows, includes Calpro_D40)
    S7: Individual food -> taxon (28,000 rows)

Significance criterion (per the paper):
    FDR < 0.05 AND Het.Pval > 0.05
    (significant pooled meta-analysis AND consistent across cohorts)

Output: data/processed/triples_bolte2021.tsv
"""
import re
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import RAW_DATA, PROCESSED_DATA
from ingestion.triple import Triple, write_triples_tsv
from normalization.ontology_loader import load_ontology, search_ontology
from normalization.ncbi_taxonomy import load_cache as load_ncbi_cache, search_microbe

BOLTE_DIR = RAW_DATA / "bolte2021"
OUTPUT = PROCESSED_DATA / "triples_bolte2021.tsv"

FDR_THRESHOLD = 0.05
HET_PVAL_THRESHOLD = 0.05

# Calprotectin and chromogranin A are the inflammatory markers in S5
MARKER_MAP = {
    "Calpro_D40": ("HP:0040156", "elevated fecal calprotectin", "IBD_Outcome"),
    # ChrA (chromogranin A) is also in S5 but is more general; we'll record it
    "ChrA":       ("UBERON:NA",   "chromogranin A level",       "IBD_Outcome"),
}


def step(msg):
    print(f"\n=== {msg} ===  [{time.strftime('%H:%M:%S')}]", flush=True)


def parse_metaphlan_taxa(taxa_str):
    """Parse MetaPhlAn-style taxa string into the most specific taxonomic name.

    Example input: 'k__Bacteria.p__Firmicutes.c__Bacilli.o__Lactobacillales.f__Lactobacillaceae.g__Lactobacillus.s__Lactobacillus_delbrueckii'

    Returns the most specific level: ('Lactobacillus delbrueckii', 'species')
    Or:    ('Lactobacillus', 'genus') if no species,
           ('Lactobacillaceae', 'family') if no genus, etc.
    """
    if pd.isna(taxa_str):
        return None, None

    parts = str(taxa_str).split('.')
    rank_prefixes = {
        's__': 'species',
        'g__': 'genus',
        'f__': 'family',
        'o__': 'order',
        'c__': 'class',
        'p__': 'phylum',
        'k__': 'kingdom',
    }
    # Walk from most specific (species) to least, find the first one with a name
    for prefix, rank in [('s__', 'species'), ('g__', 'genus'), ('f__', 'family'),
                          ('o__', 'order'), ('c__', 'class'), ('p__', 'phylum'),
                          ('k__', 'kingdom')]:
        for part in parts:
            if part.startswith(prefix):
                name = part[len(prefix):].strip()
                if name and 'unclassified' not in name.lower() and name != 'NA':
                    # MetaPhlAn uses underscores for spaces in species names
                    return name.replace('_', ' '), rank
    return None, None


_BOLTE_FOOD_MAPPING_CACHE = None

def load_bolte_food_mappings():
    """Load manual Bolte food -> FoodOn name mappings."""
    global _BOLTE_FOOD_MAPPING_CACHE
    if _BOLTE_FOOD_MAPPING_CACHE is not None:
        return _BOLTE_FOOD_MAPPING_CACHE
    mapping_file = PROCESSED_DATA / "bolte_food_mappings.tsv"
    if not mapping_file.exists():
        _BOLTE_FOOD_MAPPING_CACHE = {}
        return _BOLTE_FOOD_MAPPING_CACHE
    df = pd.read_csv(mapping_file, sep='\t')
    _BOLTE_FOOD_MAPPING_CACHE = {
        str(row['bolte_food']).strip().lower(): str(row['foodon_label']).strip()
        for _, row in df.iterrows()
        if pd.notna(row['foodon_label']) and str(row['foodon_label']).strip() not in ('-', '')
    }
    return _BOLTE_FOOD_MAPPING_CACHE


def normalize_food_name(food_str):
    """Normalize Bolte's food name for FoodOn lookup.

    Strategy:
      1. Check manual Bolte->FoodOn mapping table first
      2. Otherwise strip 'group_' prefix and underscores
    """
    if pd.isna(food_str):
        return None
    name = str(food_str).strip()

    # Manual mapping takes priority
    mappings = load_bolte_food_mappings()
    if name.lower() in mappings:
        return mappings[name.lower()]

    # Heuristic fallback
    if name.startswith("group_"):
        name = name[6:]
    name = name.replace('_', ' ').strip()
    name = re.sub(r'\blf\b', 'low-fat', name)
    name = re.sub(r'\s+', ' ', name)
    return name


def confidence_from_fdr(fdr):
    """Map FDR to confidence: stronger evidence = higher confidence."""
    if pd.isna(fdr):
        return 0.5
    if fdr < 1e-10:
        return 0.95
    elif fdr < 1e-5:
        return 0.92
    elif fdr < 1e-3:
        return 0.88
    elif fdr < 0.01:
        return 0.85
    elif fdr < 0.05:
        return 0.80
    return 0.5


def ingest_s7(foodon, ncbi_cache):
    """Individual food -> taxon associations."""
    step("Ingesting S7: individual food -> taxon (28,000 rows)")

    df = pd.read_excel(
        BOLTE_DIR / "gutjnl-2020-322670supp007_data_supplement.xlsx",
        sheet_name="S7_Taxa_Individual_foods",
        skiprows=7,
    )
    print(f"  Loaded {len(df):,} rows")
    for col in ['FDR', 'Het.Pval', 'beta']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    # Apply significance filter
    significant = df[
        (df['FDR'].notna()) &
        (df['FDR'] < FDR_THRESHOLD) &
        (df['Het.Pval'].notna()) &
        (df['Het.Pval'] > HET_PVAL_THRESHOLD)
    ].copy()
    print(f"  After FDR<{FDR_THRESHOLD} AND Het.Pval>{HET_PVAL_THRESHOLD}: {len(significant):,} rows")

    triples = []
    skip_no_microbe = 0
    skip_no_food = 0
    seen = set()  # Deduplicate identical (taxon, food, predicate) triples

    for _, row in significant.iterrows():
        taxa_name, taxa_rank = parse_metaphlan_taxa(row['Taxa'])
        food_name = normalize_food_name(row['Food'])
        beta = row['beta']

        if not taxa_name or not food_name:
            continue

        # Resolve microbe via NCBI Taxonomy
        ncbi_results = search_microbe(taxa_name, ncbi_cache, max_results=1)
        if not ncbi_results:
            skip_no_microbe += 1
            continue
        tax_id, tax_label, _, _ = ncbi_results[0]
        microbe_id = f"NCBITaxon:{tax_id}"

        # Resolve food via FoodOn
        food_results = search_ontology(foodon, food_name, max_results=1, return_match_type=True)
        if not food_results or food_results[0][3] not in ('exact_label', 'exact_synonym'):
            skip_no_food += 1
            continue
        food_id, food_label, _, _ = food_results[0]

        # Predicate based on effect direction
        predicate = "increases_abundance_of" if beta > 0 else "decreases_abundance_of"

        # Deduplication key
        dedup_key = (food_id, predicate, microbe_id)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        confidence = confidence_from_fdr(row['FDR'])

        triple = Triple(
            subject_id=food_id,
            subject_label=food_label,
            subject_type="Food",
            predicate=predicate,
            object_id=microbe_id,
            object_label=tax_label,
            object_type="Microbe",
            source="Bolte2021",
            source_id=f"S7:{row['Taxa']}|{row['Food']}",
            publication_id="10.1136/gutjnl-2020-322670",
            evidence_type="observational",
            confidence=confidence,
            sample_type="Faeces",
            method="shotgun metagenomics + FFQ; meta-analysis across 4 cohorts (n=1425)",
            notes=f"beta={beta:.3g}; FDR={row['FDR']:.2g}; Het.Pval={row['Het.Pval']:.2g}; rank={taxa_rank}",
        )
        triples.append(triple)

    print(f"  Triples emitted:       {len(triples):,}")
    print(f"  Skipped (no microbe):  {skip_no_microbe:,}")
    print(f"  Skipped (food unmapped): {skip_no_food:,}")
    return triples


def ingest_s4(ncbi_cache):
    """Food cluster -> bacterial cluster associations.

    Food clusters and bacterial clusters are paper-specific, not normalizable
    to standard ontologies. We emit triples with cluster identifiers and the
    paper-defined cluster definitions go to docs/.
    """
    step("Ingesting S4: food cluster -> bacterial cluster (725 rows)")

    df = pd.read_excel(
        BOLTE_DIR / "gutjnl-2020-322670supp005_data_supplement.xlsx",
        sheet_name="S4_Tax_clusters",
        skiprows=8,
    )
    print(f"  Loaded {len(df):,} rows")
    # Coerce statistical columns to numeric; 'NS' and similar become NaN
    for col in ['FDR', 'Het.Pval', 'beta']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    significant = df[
        (df['FDR'].notna()) &
        (df['FDR'] < FDR_THRESHOLD) &
        (df['Het.Pval'].notna()) &
        (df['Het.Pval'] > HET_PVAL_THRESHOLD)
    ].copy()
    print(f"  After significance filter: {len(significant):,} rows")

    triples = []
    for _, row in significant.iterrows():
        species_cluster = str(row['Species cluster']).strip()
        food_cluster = str(row['Food cluster']).strip()
        beta = row['beta']

        if not species_cluster or not food_cluster:
            continue

        # Cluster IDs are paper-specific (S1_Acetate/butyrate producers etc.)
        food_id = f"BOLTE_FOOD_CLUSTER:{food_cluster.replace(' ', '_').replace('/', '_')}"
        microbe_id = f"BOLTE_MICROBE_CLUSTER:{species_cluster.replace(' ', '_').replace('/', '_')[:80]}"

        predicate = "modulates_cluster" if beta > 0 else "modulates_cluster"
        # Use direction in notes instead since cluster relationships are bidirectional
        direction = "positive" if beta > 0 else "negative"

        triple = Triple(
            subject_id=food_id,
            subject_label=food_cluster,
            subject_type="Food",
            predicate="modulates_cluster",
            object_id=microbe_id,
            object_label=species_cluster[:80],
            object_type="Microbe",
            source="Bolte2021",
            source_id=f"S4:{species_cluster[:30]}|{food_cluster}",
            publication_id="10.1136/gutjnl-2020-322670",
            evidence_type="observational",
            confidence=confidence_from_fdr(row['FDR']),
            sample_type="Faeces",
            method="cluster-level meta-analysis",
            notes=f"direction={direction}; beta={beta:.3g}; FDR={row['FDR']:.2g}",
        )
        triples.append(triple)

    print(f"  Triples emitted: {len(triples):,}")
    return triples


def ingest_s5():
    """Food cluster -> inflammatory marker associations.

    This is the gold: dietary pattern -> calprotectin (IBD biomarker) edges.
    """
    step("Ingesting S5: food cluster -> calprotectin / ChrA (50 rows)")

    df = pd.read_excel(
        BOLTE_DIR / "gutjnl-2020-322670supp006_data_supplement.xlsx",
        sheet_name="S5_Markers_food_clusters",
        skiprows=9,
    )
    print(f"  Loaded {len(df):,} rows")
    for col in ['FDR', 'Het.Pval', 'beta']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    significant = df[
        (df['FDR'].notna()) &
        (df['FDR'] < FDR_THRESHOLD) &
        (df['Het.Pval'].notna()) &
        (df['Het.Pval'] > HET_PVAL_THRESHOLD)
    ].copy()
    print(f"  After significance filter: {len(significant):,} rows")

    triples = []
    for _, row in significant.iterrows():
        marker = str(row['Marker']).strip()
        food_cluster = str(row['Food cluster']).strip()
        beta = row['beta']

        marker_info = MARKER_MAP.get(marker)
        if not marker_info:
            print(f"  Skipping unknown marker: {marker}")
            continue
        marker_id, marker_label, marker_type = marker_info

        food_id = f"BOLTE_FOOD_CLUSTER:{food_cluster.replace(' ', '_').replace('/', '_')}"

        predicate = "increases_marker" if beta > 0 else "decreases_marker"

        triple = Triple(
            subject_id=food_id,
            subject_label=food_cluster,
            subject_type="Food",
            predicate=predicate,
            object_id=marker_id,
            object_label=marker_label,
            object_type=marker_type,
            source="Bolte2021",
            source_id=f"S5:{marker}|{food_cluster}",
            publication_id="10.1136/gutjnl-2020-322670",
            evidence_type="observational",
            confidence=confidence_from_fdr(row['FDR']),
            sample_type="Faeces",
            method="meta-analysis of 4 cohorts (n=1425)",
            notes=f"beta={beta:.3g}; FDR={row['FDR']:.2g}; Het.Pval={row['Het.Pval']:.2g}",
        )
        triples.append(triple)

    print(f"  Triples emitted: {len(triples):,}")
    return triples


def main():
    overall_start = time.time()

    print("Loading FoodOn ontology...")
    foodon = load_ontology("foodon.owl")
    print(f"  {len(foodon):,} FoodOn terms loaded")

    print("\nLoading NCBI Taxonomy cache...")
    ncbi_cache = load_ncbi_cache()
    print(f"  {len(ncbi_cache['tax_to_names']):,} taxa loaded")

    triples = []
    triples.extend(ingest_s5())  # Most clinically valuable
    triples.extend(ingest_s4(ncbi_cache))
    triples.extend(ingest_s7(foodon, ncbi_cache))

    step("Summary")
    print(f"  Total triples: {len(triples):,}")

    by_source_table = Counter(t.source_id.split(':')[0] for t in triples)
    print(f"  By source table:")
    for sheet, count in by_source_table.most_common():
        print(f"    {sheet}: {count}")

    by_predicate = Counter(t.predicate for t in triples)
    print(f"  By predicate:")
    for pred, count in by_predicate.most_common():
        print(f"    {pred}: {count}")

    write_triples_tsv(triples, OUTPUT)
    print(f"\nWrote {len(triples):,} triples to {OUTPUT}")
    print(f"  File size: {OUTPUT.stat().st_size / 1024:.1f} KB")

    print(f"\nTotal runtime: {time.time() - overall_start:.1f}s")

    # Show a few S5 (calprotectin) triples since these are the clinically important ones
    s5_triples = [t for t in triples if t.source_id.startswith("S5:")]
    if s5_triples:
        print(f"\n=== Sample S5 (diet -> calprotectin/ChrA) triples ===")
        for t in s5_triples[:10]:
            print(f"  {t.subject_label:<40} --[{t.predicate}]--> {t.object_label}  "
                  f"(conf={t.confidence}, {t.notes[:50]})")


if __name__ == "__main__":
    main()
