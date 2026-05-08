"""Manual ontology mappings for entities that don't resolve via cascaded search.

These are typically abbreviations (TMAO, EGCG, LPS) or compounds where ChEBI's
canonical label uses IUPAC chemistry conventions different from biology literature.
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import PROCESSED_DATA


def load_manual_mappings(filename="manual_chebi_mappings.tsv"):
    """Load TSV of manual mappings: common_name -> dict(id, label, notes)."""
    filepath = PROCESSED_DATA / filename
    if not filepath.exists():
        return {}
    mappings = {}
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            key = row["common_name"].lower().strip()
            mappings[key] = {
                "id": row["chebi_id"],
                "label": row["chebi_label"],
                "notes": row.get("notes", ""),
            }
    return mappings


def lookup_with_manual_fallback(query, entries, search_func, manual_mappings=None):
    """Try cascaded search first, fall back to manual mapping if no exact match.

    Returns (id, label, match_type). match_type values:
      - exact_label / exact_synonym (from cascaded search)
      - manual_mapping (resolved via manual table)
      - label_starts_with / tokenized_label / substring_label / substring_synonym
        (cascaded search returned a non-exact result and no manual override)
      - no_match
    """
    if manual_mappings is None:
        manual_mappings = load_manual_mappings()

    results = search_func(entries, query, max_results=1, return_match_type=True)
    if results:
        eid, label, _, match_type = results[0]
        if match_type in ("exact_label", "exact_synonym"):
            return eid, label, match_type

    key = query.lower().strip()
    if key in manual_mappings:
        m = manual_mappings[key]
        return m["id"], m["label"], "manual_mapping"

    if results:
        eid, label, _, match_type = results[0]
        return eid, label, match_type
    return None, None, "no_match"


if __name__ == "__main__":
    from src.normalization.ontology_loader import load_ontology, search_ontology

    print("Loading ChEBI...")
    chebi = load_ontology("chebi.obo")

    mappings = load_manual_mappings()
    print(f"Loaded {len(mappings)} manual mappings\n")

    test_cases = ["butyrate", "TMAO", "EGCG", "LPS", "EPA", "betaine", "curcumin"]
    print(f"{'Query':<15} {'ID':<14} {'Label':<50} {'Match type':<18}")
    print("-" * 100)
    for compound in test_cases:
        eid, label, match_type = lookup_with_manual_fallback(
            compound, chebi, search_ontology, mappings
        )
        marker = "✓" if match_type in ("exact_label", "exact_synonym", "manual_mapping") else "?"
        print(f"  {marker} {compound:<13} {eid or '(none)':<14} {(label or '(none)'):<50} {match_type}")
