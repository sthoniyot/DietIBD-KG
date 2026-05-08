"""Verify that every manual mapping in manual_chebi_mappings.tsv exists in ChEBI
and matches the label written in the notes column.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.normalization.ontology_loader import load_ontology
from src.normalization.manual_mappings import load_manual_mappings


def main():
    print("Loading ChEBI...")
    chebi = load_ontology("chebi.obo")
    chebi_by_id = {entry[0]: entry for entry in chebi}
    print(f"  {len(chebi_by_id):,} terms indexed\n")

    print("Verifying manual mappings against ChEBI...")
    print(f"{'Common name':<28} {'Mapped ID':<14} {'Status':<10} ChEBI label")
    print("-" * 105)

    mappings = load_manual_mappings()
    issues = []

    for common_name, info in sorted(mappings.items()):
        chebi_id = info["id"]
        expected = info["label"]

        if chebi_id not in chebi_by_id:
            print(f"  X {common_name:<26} {chebi_id:<14} NOT_FOUND  not in ChEBI")
            issues.append((common_name, chebi_id, "not_found"))
            continue

        actual = chebi_by_id[chebi_id][1]
        if actual and expected.lower() == actual.lower():
            print(f"  + {common_name:<26} {chebi_id:<14} OK         {actual}")
        else:
            print(f"  ! {common_name:<26} {chebi_id:<14} MISMATCH   actual: {actual}")
            issues.append((common_name, chebi_id, f"actual={actual}, expected={expected}"))

    print()
    if issues:
        print(f"! {len(issues)} mapping(s) need attention:")
        for name, cid, reason in issues:
            print(f"    {name} ({cid}): {reason}")
    else:
        print("+ All mappings verified against current ChEBI release")


if __name__ == "__main__":
    main()
