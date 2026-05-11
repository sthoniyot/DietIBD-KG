"""Filter the raw FooDB triples down to high-quality IBD-relevant bioactives.

Strategy:
- Keep only triples from the 38 allow-list compounds (curated IBD bioactives)
- Drop triples where the food is a Linnean binomial (taxonomic species name,
  not a food product). These are taxonomy artifacts, not food entities.
- Output: data/processed/triples_foodb_filtered.tsv (~17K-20K expected)

The raw triples_foodb.tsv is preserved for reproducibility.
"""
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import PROCESSED_DATA

# The 38 allow-list FooDB compound IDs we curated
ALLOWLIST_COMPOUND_IDS = {
    30807, 3293, 12295, 31375, 11907, 633, 2571, 17707, 12611, 31083,
    2250, 446, 12663, 14542, 11831, 2608, 698, 3103, 12465, 11875,
    12861, 1141, 5763, 23325, 1182, 18710, 661, 12323, 12531, 1145,
    1982, 1134, 371, 9021, 710, 11947, 10415, 12599,
}


def is_linnean_binomial(label):
    """Detect taxonomic species names like 'Triticum aestivum'.
    
    Heuristic: 2+ words, first word capitalized 4+ chars, second word lowercase.
    Genus names are usually 4+ characters (Sus is short but common).
    """
    if pd.isna(label):
        return False
    parts = str(label).split()
    if len(parts) < 2:
        return False
    first, second = parts[0], parts[1]
    # First word: starts with uppercase, all-letter
    if not (first[0].isupper() and first.isalpha()):
        return False
    # Second word: starts with lowercase, all-letter
    if not (second[0].islower() and second.replace('-', '').isalpha()):
        return False
    # Exclude common multi-word food labels that aren't taxa
    # (e.g., "common bean", "wheat bread", "food for")
    common_food_starts = {"common", "wheat", "food", "rice", "corn",
                          "white", "whole", "ground", "fresh", "raw"}
    if first.lower() in common_food_starts:
        return False
    return True


def main():
    input_path = PROCESSED_DATA / "triples_foodb.tsv"
    output_path = PROCESSED_DATA / "triples_foodb_filtered.tsv"

    print(f"Loading {input_path}...")
    df = pd.read_csv(input_path, sep='\t')
    print(f"  {len(df):,} triples loaded")

    print("\n=== Filter 1: Keep only allow-list compounds ===")
    df['source_id_int'] = pd.to_numeric(df['source_id'], errors='coerce')
    allow_df = df[df['source_id_int'].isin(ALLOWLIST_COMPOUND_IDS)].copy()
    print(f"  After allow-list filter: {len(allow_df):,} triples")
    print(f"  Dropped: {len(df) - len(allow_df):,} (classified-only compounds)")

    print("\n=== Filter 2: Drop Linnean binomial foods ===")
    allow_df['is_binomial'] = allow_df['subject_label'].apply(is_linnean_binomial)
    binomials_dropped = allow_df[allow_df['is_binomial']]['subject_label'].value_counts().head(15)
    print(f"  Dropping {allow_df['is_binomial'].sum():,} triples with binomial food labels")
    print(f"\n  Top binomial foods being dropped:")
    print(binomials_dropped.to_string())

    final_df = allow_df[~allow_df['is_binomial']].copy()
    final_df = final_df.drop(columns=['source_id_int', 'is_binomial'])

    print(f"\n=== Final output ===")
    print(f"  Triples retained: {len(final_df):,}")

    # Distribution
    print(f"\n  Top 15 compounds in filtered set:")
    print(final_df['object_label'].value_counts().head(15).to_string())

    print(f"\n  Top 15 foods in filtered set:")
    print(final_df['subject_label'].value_counts().head(15).to_string())

    # Save
    final_df.to_csv(output_path, sep='\t', index=False)
    size_kb = output_path.stat().st_size / 1024
    print(f"\nWrote {len(final_df):,} triples to {output_path} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
