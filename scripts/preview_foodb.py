"""Preview what the FooDB ingestion will do before running the full pipeline.

Reports:
- How many allow-list compounds match in FooDB
- How many IBD-relevant classified compounds exist
- ChEBI mapping coverage
- Food-to-FoodOn match coverage

This is a 1-2 minute diagnostic. Run before ingest_foodb.py.
"""
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import RAW_DATA, PROCESSED_DATA
from src.normalization.ontology_loader import load_ontology, search_ontology

FOODB_DIR = RAW_DATA / "foodb" / "foodb_2020_04_07_csv"
ALLOWLIST = PROCESSED_DATA / "foodb_compound_allowlist.tsv"

# Superklass values we consider IBD-relevant for unclassified-aware filtering
IBD_RELEVANT_SUPERKLASSES = {
    "Lipids and lipid-like molecules",
    "Phenylpropanoids and polyketides",
    "Organic acids and derivatives",
    "Organoheterocyclic compounds",
    "Organooxygen compounds",
    "Organosulfur compounds",
    "Lignans, neolignans and related compounds",
    "Alkaloids and derivatives",
    "Nucleosides, nucleotides, and analogues",
}

def load_allowlist():
    """Load manual allow-list of IBD-relevant compound names."""
    df = pd.read_csv(ALLOWLIST, sep='\t')
    return df

def load_compounds():
    """Load Compound.csv with key columns, robust to malformed rows."""
    print("Loading Compound.csv...")
    df = pd.read_csv(
        FOODB_DIR / "Compound.csv",
        encoding='utf-8',
        engine='python',
        on_bad_lines='skip',
        usecols=['id', 'name', 'kingdom', 'superklass', 'klass', 'subklass'],
    )
    print(f"  {len(df):,} compounds loaded")
    return df

def find_allowlist_matches(allowlist_df, compounds_df):
    """For each allow-list name, find matching FooDB compounds (case-insensitive).
    
    Returns dict: allowlist_name -> list of (compound_id, compound_name)
    """
    print("\n=== Allow-list matches in FooDB ===")
    compounds_df['name_lower'] = compounds_df['name'].fillna('').str.lower()
    matches = {}
    total_matched_ids = set()
    
    for _, row in allowlist_df.iterrows():
        name = row['common_name']
        name_lower = name.lower().strip()
        
        # Exact match first
        exact = compounds_df[compounds_df['name_lower'] == name_lower]
        # Substring match as backup
        substr = compounds_df[compounds_df['name_lower'].str.contains(name_lower, regex=False, na=False)]
        
        # Exact only - substring matches wrong compounds (esters, derivatives)
        if len(exact) > 0:
            ids = exact['id'].tolist()[:3]
            names = exact['name'].tolist()[:3]
            match_type = "exact"
        else:
            ids, names = [], []
            match_type = "no_exact"
        
        if ids:
            total_matched_ids.update(ids)
            print(f"  + {name:<35} [{match_type:<9}] -> {len(ids)} match(es), e.g. id={ids[0]}: {names[0]}")
        else:
            print(f"  X {name:<35} [no match]")
        
        matches[name] = list(zip(ids, names))
    
    found = sum(1 for v in matches.values() if v)
    print(f"\n  Allow-list coverage: {found}/{len(allowlist_df)} compounds findable in FooDB")
    print(f"  Unique compound IDs from allow-list: {len(total_matched_ids)}")
    return matches, total_matched_ids


def find_classified_compounds(compounds_df):
    """Return IDs of compounds in IBD-relevant superklasses."""
    print("\n=== Classified IBD-relevant compounds ===")
    classified = compounds_df[compounds_df['superklass'].isin(IBD_RELEVANT_SUPERKLASSES)]
    print(f"  {len(classified):,} compounds in IBD-relevant superklasses")
    by_super = classified['superklass'].value_counts()
    for sk, c in by_super.head(10).items():
        print(f"    {sk:<50} {c:>5}")
    return set(classified['id'].tolist())


def estimate_chebi_coverage(compound_ids):
    """Quick estimate: how many of these compounds have ChEBI synonyms?"""
    print("\n=== ChEBI mapping coverage estimate ===")
    print("Streaming CompoundSynonym.csv (this takes ~30s)...")
    
    chebi_count = 0
    with_chebi = set()
    
    chunks = pd.read_csv(
        FOODB_DIR / "CompoundSynonym.csv",
        encoding='utf-8',
        engine='python',
        on_bad_lines='skip',
        usecols=['source_id', 'source_type', 'synonym_source', 'synonym'],
        chunksize=20000,
    )
    
    for chunk in chunks:
        chunk['synonym_source_norm'] = chunk['synonym_source'].fillna('').str.upper()
        chebi_chunk = chunk[
            (chunk['synonym_source_norm'].str.contains('CHEBI', na=False)) &
            (chunk['source_type'] == 'Compound') &
            (chunk['source_id'].isin(compound_ids))
        ]
        chebi_count += len(chebi_chunk)
        with_chebi.update(chebi_chunk['source_id'].tolist())
    
    print(f"  ChEBI synonyms for our compound subset: {chebi_count}")
    print(f"  Unique compounds with at least one ChEBI synonym: {len(with_chebi)}")
    print(f"  ChEBI coverage: {100*len(with_chebi)/len(compound_ids):.1f}% of our subset")
    return with_chebi


def estimate_food_coverage():
    """How many FooDB foods resolve to FoodOn?"""
    print("\n=== Food-to-FoodOn coverage ===")
    food_df = pd.read_csv(FOODB_DIR / "Food.csv", encoding='utf-8', on_bad_lines='skip')
    print(f"  {len(food_df)} foods loaded")
    
    print("  Loading FoodOn (cached)...")
    foodon = load_ontology("foodon.owl")
    
    matched = 0
    sample_misses = []
    sample_hits = []
    
    for _, row in food_df.iterrows():
        name = str(row['name']).strip() if pd.notna(row['name']) else ''
        if not name:
            continue
        results = search_ontology(foodon, name, max_results=1, return_match_type=True)
        if results and results[0][3] in ('exact_label', 'exact_synonym'):
            matched += 1
            if len(sample_hits) < 5:
                sample_hits.append((name, results[0][0], results[0][1], results[0][3]))
        else:
            if len(sample_misses) < 5:
                sample_misses.append(name)
    
    print(f"  Foods with exact/synonym FoodOn match: {matched}/{len(food_df)} ({100*matched/len(food_df):.1f}%)")
    print(f"  Sample matches:")
    for n, fid, lab, mt in sample_hits:
        print(f"    + {n:<25} -> {fid}: {lab} [{mt}]")
    print(f"  Sample misses:")
    for n in sample_misses:
        print(f"    X {n}")


def estimate_content_volume(compound_ids):
    """Estimate how many Content.csv rows will pass the filter."""
    print("\n=== Content.csv volume estimate (sampling first 200K rows) ===")
    
    chunk = pd.read_csv(
        FOODB_DIR / "Content.csv",
        encoding='utf-8',
        engine='python',
        on_bad_lines='skip',
        usecols=['source_id', 'source_type', 'food_id', 'standard_content'],
        nrows=200000,
    )
    
    filtered = chunk[
        (chunk['source_type'] == 'Compound') &
        (chunk['source_id'].isin(compound_ids)) &
        (chunk['standard_content'].notna())
    ]
    
    pct = 100 * len(filtered) / len(chunk)
    full_estimate = int(5145533 * pct / 100)
    
    print(f"  In first 200K rows: {len(filtered)} pass filter ({pct:.2f}%)")
    print(f"  Extrapolated to full 5.1M rows: ~{full_estimate:,} triples")


def main():
    allowlist = load_allowlist()
    print(f"Allow-list: {len(allowlist)} compounds")
    
    compounds = load_compounds()
    
    _, allowlist_ids = find_allowlist_matches(allowlist, compounds)
    classified_ids = find_classified_compounds(compounds)
    
    all_ids = allowlist_ids | classified_ids
    print(f"\n=== Total IBD-relevant compound subset ===")
    print(f"  Allow-list: {len(allowlist_ids)}")
    print(f"  Classified: {len(classified_ids)}")
    print(f"  Union:      {len(all_ids)}")
    
    estimate_chebi_coverage(all_ids)
    estimate_food_coverage()
    estimate_content_volume(all_ids)
    
    print("\n=== Preview complete ===")
    print("If counts look reasonable, run: python -m src.ingestion.ingest_foodb")


if __name__ == "__main__":
    main()
