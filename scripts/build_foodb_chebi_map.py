"""Build FooDB compound_id -> real ChEBI ID mapping using ChEBI ontology lookup.

For each FooDB compound in our target subset:
  1. Try exact match on primary compound name
  2. Try exact match on each 'ChEBI'-sourced synonym (these are chemistry-correct
     alternative names per ChEBI's records)
  3. Try manual mapping fallback
  4. Skip if no match

Outputs:
  data/processed/foodb_chebi_mapping.tsv  - confirmed mappings
"""
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import RAW_DATA, PROCESSED_DATA
from src.normalization.ontology_loader import load_ontology, search_ontology
from src.normalization.manual_mappings import load_manual_mappings, lookup_with_manual_fallback

FOODB_DIR = RAW_DATA / "foodb" / "foodb_2020_04_07_csv"

# Allow-list FooDB compound IDs (the 38 we curated)
ALLOWLIST_COMPOUND_IDS = {
    30807, 3293, 12295, 31375, 11907, 633, 2571, 17707, 12611, 31083,
    2250, 446, 12663, 14542, 11831, 2608, 698, 3103, 12465, 11875,
    12861, 1141, 5763, 23325, 1182, 18710, 661, 12323, 12531, 1145,
    1982, 1134, 371, 9021, 710, 11947, 10415, 12599,
}

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


def main():
    print("Loading Compound.csv...")
    compounds = pd.read_csv(
        FOODB_DIR / "Compound.csv",
        encoding='utf-8',
        engine='python',
        on_bad_lines='skip',
        usecols=['id', 'name', 'superklass'],
    )
    print(f"  {len(compounds):,} compounds")

    # Subset to allow-list + classified IBD-relevant
    target_ids = set(ALLOWLIST_COMPOUND_IDS) | set(
        compounds[compounds['superklass'].isin(IBD_RELEVANT_SUPERKLASSES)]['id'].tolist()
    )
    print(f"  Target subset: {len(target_ids):,} compounds")

    print("\nLoading CompoundSynonym.csv (for ChEBI-sourced synonyms)...")
    syn_df = pd.read_csv(
        FOODB_DIR / "CompoundSynonym.csv",
        encoding='utf-8',
        engine='python',
        on_bad_lines='skip',
        usecols=['source_id', 'source_type', 'synonym_source', 'synonym'],
    )
    chebi_syns = syn_df[
        (syn_df['source_type'] == 'Compound') &
        (syn_df['synonym_source'].fillna('').str.upper() == 'CHEBI') &
        (syn_df['source_id'].isin(target_ids))
    ].copy()
    # Group synonyms by compound
    syn_lookup = chebi_syns.groupby('source_id')['synonym'].apply(list).to_dict()
    print(f"  {len(chebi_syns):,} ChEBI-sourced synonyms across {len(syn_lookup)} compounds")

    print("\nLoading ChEBI ontology (cached)...")
    chebi = load_ontology("chebi.obo")
    manual_mappings = load_manual_mappings()
    print(f"  {len(chebi):,} ChEBI terms")

    # Map each compound
    print("\nMapping compounds to ChEBI IDs...")
    mappings = []
    by_match_source = {"primary_name": 0, "chebi_synonym": 0, "manual": 0, "no_match": 0}

    compound_subset = compounds[compounds['id'].isin(target_ids)]

    for i, row in enumerate(compound_subset.itertuples(index=False)):
        cid = row.id
        cname = str(row.name).strip() if pd.notna(row.name) else ''

        if not cname:
            by_match_source["no_match"] += 1
            continue

        # 1) Try the primary name with manual fallback
        chebi_id, chebi_label, match_type = lookup_with_manual_fallback(
            cname, chebi, search_ontology, manual_mappings
        )
        if chebi_id and match_type in ("exact_label", "exact_synonym", "manual_mapping"):
            mappings.append({
                'foodb_compound_id': cid,
                'foodb_compound_name': cname,
                'chebi_id': chebi_id,
                'chebi_label': chebi_label,
                'match_source': "primary_name" if match_type != "manual_mapping" else "manual",
                'match_type': match_type,
            })
            by_match_source["primary_name" if match_type != "manual_mapping" else "manual"] += 1
            continue

        # 2) Try ChEBI-sourced synonyms
        matched_via_synonym = False
        for syn in syn_lookup.get(cid, []):
            syn_clean = str(syn).strip()
            results = search_ontology(chebi, syn_clean, max_results=1, return_match_type=True)
            if results and results[0][3] in ("exact_label", "exact_synonym"):
                chebi_id, chebi_label, _, mt = results[0]
                mappings.append({
                    'foodb_compound_id': cid,
                    'foodb_compound_name': cname,
                    'chebi_id': chebi_id,
                    'chebi_label': chebi_label,
                    'match_source': "chebi_synonym",
                    'match_type': mt,
                })
                by_match_source["chebi_synonym"] += 1
                matched_via_synonym = True
                break

        if not matched_via_synonym:
            by_match_source["no_match"] += 1

        if (i + 1) % 500 == 0:
            print(f"  Progress: {i+1:,}/{len(compound_subset):,}  "
                  f"matched so far: {len(mappings):,}")

    print(f"\nMapping summary:")
    print(f"  Total mappings:           {len(mappings):,}")
    print(f"    via primary name:       {by_match_source['primary_name']:,}")
    print(f"    via ChEBI synonym:      {by_match_source['chebi_synonym']:,}")
    print(f"    via manual mapping:     {by_match_source['manual']:,}")
    print(f"  Unmapped (dropped):       {by_match_source['no_match']:,}")
    print(f"  Coverage:                 {100*len(mappings)/len(compound_subset):.1f}%")

    # Verify a few well-known compounds resolved correctly
    print(f"\n=== Verification of well-known compounds ===")
    expected = {
        11907: ("Quercetin", "CHEBI:16243"),
        12295: ("Curcumin", "CHEBI:3962"),
        3103:  ("EPA", "CHEBI:28364"),
        11875: ("Arachidonic acid", "CHEBI:15843"),
        1145:  ("Lactose", "CHEBI:36219"),
        2250:  ("L-Tryptophan", "CHEBI:16828"),
        446:   ("L-Tyrosine", "CHEBI:17895"),
        30807: ("Acetate", "CHEBI:30089"),
        12611: ("Sulforaphane", "CHEBI:47807"),
    }
    by_cid = {m['foodb_compound_id']: m for m in mappings}
    for cid, (name, expected_chebi) in expected.items():
        m = by_cid.get(cid)
        if m:
            mark = "+" if m['chebi_id'] == expected_chebi else "?"
            print(f"  {mark} {name:<25} -> {m['chebi_id']:<14} (expected {expected_chebi})  via {m['match_source']}")
        else:
            print(f"  X {name:<25} -> NOT MAPPED")

    # Save mappings
    out_df = pd.DataFrame(mappings)
    output_path = PROCESSED_DATA / "foodb_chebi_mapping.tsv"
    out_df.to_csv(output_path, sep='\t', index=False)
    print(f"\nWrote {len(out_df):,} mappings to {output_path}")


if __name__ == "__main__":
    main()
