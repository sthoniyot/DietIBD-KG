"""Ingest KEGG pathway -> metabolite associations for IBD-relevant pathways.

For each of 15 curated IBD-relevant KEGG pathways:
  1. Fetch list of compounds in the pathway (via /link/cpd/pathway:mapXXXXX)
  2. Resolve compound names from KEGG /list/compound (one bulk call)
  3. Resolve ChEBI IDs from pre-built kegg_chebi_mapping.tsv
  4. Emit triples (pathway, involves, compound) where ChEBI mapping exists

Rate limited to 1 req/sec (KEGG's policy allows 3/sec; we stay conservative).

Total API calls: 1 (compound names) + 15 (pathway compounds) = 16 calls
Expected runtime: ~20 seconds.

Output: data/processed/triples_kegg.tsv
"""
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import PROCESSED_DATA
from ingestion.triple import Triple, write_triples_tsv

PATHWAYS_TSV = PROCESSED_DATA / "kegg_ibd_pathways.tsv"
CHEBI_MAP_TSV = PROCESSED_DATA / "kegg_chebi_mapping.tsv"
OUTPUT = PROCESSED_DATA / "triples_kegg.tsv"

KEGG_BASE = "https://rest.kegg.jp"
RATE_LIMIT_SEC = 1.0  # 1 req/sec (KEGG allows 3/sec; we stay conservative)


def fetch(url, max_retries=3):
    """Fetch URL with retries and rate limiting."""
    for attempt in range(max_retries):
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            time.sleep(RATE_LIMIT_SEC)
            return r.text
        except Exception as e:
            print(f"    Attempt {attempt+1} failed: {e}")
            time.sleep(3)
    raise RuntimeError(f"Failed to fetch {url}")


def load_compound_names():
    """Fetch all KEGG compound names in one bulk call."""
    print("Fetching all KEGG compound names...")
    text = fetch(f"{KEGG_BASE}/list/compound")
    names = {}
    for line in text.strip().split("\n"):
        parts = line.split("\t", 1)
        if len(parts) == 2:
            kegg_id = parts[0].replace("cpd:", "")
            # KEGG names are semicolon-separated synonyms; first is canonical
            name = parts[1].split(";")[0].strip()
            names[kegg_id] = name
    print(f"  {len(names):,} compounds named")
    return names


def load_chebi_map():
    """Load KEGG -> ChEBI mapping."""
    df = pd.read_csv(CHEBI_MAP_TSV, sep='\t')
    mapping = dict(zip(df['kegg_id'], df['chebi_id']))
    print(f"  {len(mapping):,} ChEBI mappings loaded")
    return mapping


def main():
    print("Loading KEGG-ChEBI mapping...")
    chebi_map = load_chebi_map()

    compound_names = load_compound_names()

    print("\nLoading IBD-relevant pathway list...")
    pathways = pd.read_csv(PATHWAYS_TSV, sep='\t')
    print(f"  {len(pathways)} pathways")

    triples = []
    seen = set()
    skip_no_chebi = 0
    skip_no_name = 0

    for _, row in pathways.iterrows():
        pathway_id = row['pathway_id']
        pathway_label = row['pathway_label']
        priority = row['priority']

        print(f"\n[{pathway_id}] {pathway_label}")
        text = fetch(f"{KEGG_BASE}/link/cpd/pathway:{pathway_id}")
        if text is None:
            print(f"  No compounds returned (404)")
            continue

        compounds_in_pathway = []
        for line in text.strip().split("\n"):
            parts = line.split("\t")
            if len(parts) == 2:
                kegg_id = parts[1].replace("cpd:", "")
                compounds_in_pathway.append(kegg_id)
        print(f"  {len(compounds_in_pathway)} compounds in pathway")

        emitted_for_this_pathway = 0
        for kegg_id in compounds_in_pathway:
            chebi_id = chebi_map.get(kegg_id)
            if not chebi_id:
                skip_no_chebi += 1
                continue

            compound_name = compound_names.get(kegg_id)
            if not compound_name:
                skip_no_name += 1
                continue

            confidence = 0.92 if priority == 'high' else 0.88
            pathway_kg_id = f"KEGG:{pathway_id}"

            dedup_key = (pathway_kg_id, "involves", chebi_id)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            triple = Triple(
                subject_id=pathway_kg_id,
                subject_label=pathway_label,
                subject_type="Pathway",
                predicate="involves",
                object_id=chebi_id,
                object_label=compound_name,
                object_type="Bioactive",
                source="KEGG",
                source_id=f"{pathway_id}|{kegg_id}",
                publication_id=None,
                evidence_type="review",
                confidence=confidence,
                sample_type=None,
                method="KEGG pathway curation",
                notes=f"KEGG compound {kegg_id}",
            )
            triples.append(triple)
            emitted_for_this_pathway += 1
        print(f"  Emitted {emitted_for_this_pathway} triples")

    print(f"\n=== Ingestion summary ===")
    print(f"  Triples emitted:           {len(triples)}")
    print(f"  Skipped (no ChEBI):        {skip_no_chebi}")
    print(f"  Skipped (no compound name):{skip_no_name}")

    if not triples:
        print("WARNING: No triples produced")
        return

    print(f"\nTriples per pathway:")
    for pathway, count in Counter(t.subject_label for t in triples).most_common():
        print(f"  ({count:>3}) {pathway}")

    write_triples_tsv(triples, OUTPUT)
    print(f"\nWrote {len(triples)} triples to {OUTPUT}")
    print(f"  File size: {OUTPUT.stat().st_size / 1024:.1f} KB")

    print(f"\n=== Sample: Butanoate metabolism triples ===")
    butyrate_triples = [t for t in triples if "Butanoate" in t.subject_label]
    for t in butyrate_triples[:10]:
        print(f"  involves: {t.object_label:<35} ({t.object_id})")

    print(f"\n=== Sample: Tryptophan metabolism triples ===")
    trp_triples = [t for t in triples if "Tryptophan metab" in t.subject_label]
    for t in trp_triples[:10]:
        print(f"  involves: {t.object_label:<35} ({t.object_id})")


if __name__ == "__main__":
    main()
