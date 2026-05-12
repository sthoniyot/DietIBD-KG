"""Build KEGG-compound -> ChEBI ID mapping from KEGG REST API.

Queries /conv/chebi/compound which returns the full KEGG compound database
with ChEBI cross-references (~5,000-6,000 entries in total).

This is a one-time build. Result is cached as TSV.

Rate limit: 3 req/sec per KEGG policy; we use 1 req/sec for safety.

Output: data/processed/kegg_chebi_mapping.tsv
"""
import sys
import time
from pathlib import Path
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import PROCESSED_DATA

OUTPUT = PROCESSED_DATA / "kegg_chebi_mapping.tsv"
KEGG_BASE = "https://rest.kegg.jp"


def fetch(url, max_retries=3):
    """Fetch a URL with retries and rate limiting."""
    for attempt in range(max_retries):
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            time.sleep(1.0)  # 1 req/sec rate limit (well under KEGG's 3/sec max)
            return r.text
        except Exception as e:
            print(f"  Attempt {attempt+1} failed: {e}")
            time.sleep(3)
    raise RuntimeError(f"Failed to fetch {url} after {max_retries} attempts")


def main():
    print("Fetching KEGG compound -> ChEBI mappings (one bulk call)...")
    text = fetch(f"{KEGG_BASE}/conv/chebi/compound")

    # Parse tab-separated: cpd:C00001\tchebi:15377
    mappings = {}
    for line in text.strip().split("\n"):
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        kegg_id = parts[0].replace("cpd:", "")
        chebi_id = parts[1].replace("chebi:", "")
        # When multiple ChEBI IDs map to one KEGG compound, prefer the smaller
        # (more canonical/parent class) ID
        if kegg_id not in mappings or int(chebi_id) < int(mappings[kegg_id]):
            mappings[kegg_id] = chebi_id

    print(f"  {len(mappings):,} unique KEGG compounds with ChEBI mapping")

    # Write to TSV
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write("kegg_id\tchebi_id\n")
        for kid, cid in sorted(mappings.items()):
            f.write(f"{kid}\tCHEBI:{cid}\n")

    print(f"Wrote {OUTPUT}")
    print(f"  File size: {OUTPUT.stat().st_size / 1024:.1f} KB")

    # Sanity check well-known compounds
    print(f"\nVerification (well-known compounds):")
    known = {
        "C00246": ("Butyric acid", "CHEBI:17968 or 30772"),
        "C00163": ("Propanoate", "CHEBI:17272"),
        "C00033": ("Acetate", "CHEBI:30089"),
        "C00074": ("Phosphoenolpyruvate", "CHEBI:18021"),
        "C00078": ("L-Tryptophan", "CHEBI:16828"),
    }
    for kegg_id, (name, expected) in known.items():
        mapped = mappings.get(kegg_id, "NOT MAPPED")
        if mapped != "NOT MAPPED":
            mapped = f"CHEBI:{mapped}"
        print(f"  {kegg_id} ({name:<25}): {mapped}  (expected ~{expected})")


if __name__ == "__main__":
    main()
