"""Build pickled cache of ontology entries for fast reload during ingestion.

Run once after downloading ontologies. Re-run if you update an ontology file.
Output: data/ontologies/cache/{ontology_name}.pkl
"""
import pickle
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import ONTOLOGY_DATA
from src.normalization.ontology_loader import load_ontology

CACHE_DIR = ONTOLOGY_DATA / "cache"
CACHE_DIR.mkdir(exist_ok=True)

ONTOLOGIES = [
    "foodon.owl",
    "chebi.obo",
    "doid.obo",
    "ncit.owl",
    "hp.obo",
]

print(f"Building ontology cache in {CACHE_DIR}\n")

for fname in ONTOLOGIES:
    cache_file = CACHE_DIR / f"{fname.split('.')[0]}.pkl"

    if cache_file.exists():
        print(f"  + {fname:<20} (cached, skipping; delete cache file to rebuild)")
        continue

    print(f"  Loading {fname}...", end=" ", flush=True)
    start = time.time()
    try:
        entries = load_ontology(fname)
        with open(cache_file, "wb") as f:
            pickle.dump(entries, f)
        elapsed = time.time() - start
        print(f"cached {len(entries):,} entries in {elapsed:.1f}s")
    except Exception as e:
        print(f"FAILED: {e}")

print("\nVerifying cache reload speeds:")
for fname in ONTOLOGIES:
    cache_file = CACHE_DIR / f"{fname.split('.')[0]}.pkl"
    if not cache_file.exists():
        continue
    start = time.time()
    with open(cache_file, "rb") as f:
        entries = pickle.load(f)
    elapsed = time.time() - start
    size_mb = cache_file.stat().st_size / 1e6
    print(f"  {fname:<20} {size_mb:>5.1f} MB cache  ->  {elapsed:>4.1f}s reload")
