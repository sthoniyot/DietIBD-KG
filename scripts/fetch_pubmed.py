"""Fetch PubMed abstracts for DietIBD-KG Phase C.

Three search streams (Option Y, free-text variants) from docs/phase_c_design.md:
  S1: Diet-microbiome-IBD core (2018-2026)
  S2: Bioactive-IBD relationships (2015-2026)
  S3: Microbe-IBD findings (2020-2026)

Process:
  1. esearch each stream to get PMIDs (paginated, ~10K results allowed)
  2. Deduplicate across streams
  3. efetch full XML records in batches of 200
  4. Parse title, abstract, year, journal, DOI, MeSH terms, publication types
  5. Cache to data/raw/pubmed/abstracts.jsonl (one JSON per line)

Rate limit: 10 req/sec with NCBI API key (we use ~5 req/sec for safety).

Resumable: if abstracts.jsonl already has PMIDs, those are skipped.

Run:
    python scripts/fetch_pubmed.py
"""
import json
import os
import sys
import time
from pathlib import Path
from typing import Iterator, Set

from dotenv import load_dotenv
from Bio import Entrez

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_PUBMED = PROJECT_ROOT / "data" / "raw" / "pubmed"
OUTPUT = RAW_PUBMED / "abstracts.jsonl"

load_dotenv(PROJECT_ROOT / ".env")
Entrez.email = os.getenv("NCBI_EMAIL")
Entrez.api_key = os.getenv("NCBI_API_KEY")
if not Entrez.email or not Entrez.api_key:
    sys.exit("ERROR: NCBI_EMAIL or NCBI_API_KEY missing from .env")

# Rate limiting: 10/sec allowed with key; we use 5/sec for safety
RATE_LIMIT_SEC = 0.20

# Per-batch sizes
ESEARCH_PAGE_SIZE = 5000   # how many PMIDs per esearch page
EFETCH_BATCH_SIZE = 200    # how many full records per efetch

STREAMS = [
    {
        "id": "S1",
        "label": "Diet-microbiome-IBD",
        "query": (
            "(inflammatory bowel disease OR Crohn OR ulcerative colitis) "
            "AND (microbiota OR microbiome) "
            "AND (diet OR nutrition OR food) "
            'AND ("2018"[PDAT] : "2026"[PDAT])'
        ),
    },
    {
        "id": "S2",
        "label": "Bioactive-IBD",
        "query": (
            "(inflammatory bowel disease OR Crohn OR ulcerative colitis) "
            'AND (butyrate OR "short chain fatty acid" OR tryptophan OR "bile acid" '
            "OR indole OR polyphenol OR \"omega-3\" OR fiber) "
            'AND ("2015"[PDAT] : "2026"[PDAT])'
        ),
    },
    {
        "id": "S3",
        "label": "Microbe-IBD",
        "query": (
            "(inflammatory bowel disease OR Crohn OR ulcerative colitis) "
            "AND (Faecalibacterium OR Akkermansia OR Roseburia OR Bacteroides "
            "OR Lactobacillus OR Bifidobacterium OR metagenomics) "
            'AND ("2020"[PDAT] : "2026"[PDAT])'
        ),
    },
]


def step(msg):
    print(f"\n=== {msg} ===  [{time.strftime('%H:%M:%S')}]", flush=True)


# ---------- Stage 1: fetch PMIDs for each stream ----------

def fetch_stream_pmids(stream_id: str, query: str) -> Set[str]:
    """Use Entrez esearch to retrieve all PMIDs for one stream."""
    print(f"\n  Stream {stream_id}: {query[:90]}...")

    # First call: get total count and the first page
    handle = Entrez.esearch(
        db="pubmed",
        term=query,
        retmax=ESEARCH_PAGE_SIZE,
        retstart=0,
        usehistory="y",
    )
    result = Entrez.read(handle)
    handle.close()
    time.sleep(RATE_LIMIT_SEC)

    total = int(result["Count"])
    web_env = result["WebEnv"]
    query_key = result["QueryKey"]
    pmids: Set[str] = set(result["IdList"])

    print(f"    Total matching: {total:,}")
    print(f"    Page 1: {len(pmids):,} PMIDs")

    # Paginate through remaining results
    page = 1
    while len(pmids) < total:
        page += 1
        retstart = (page - 1) * ESEARCH_PAGE_SIZE
        handle = Entrez.esearch(
            db="pubmed",
            term=query,
            retmax=ESEARCH_PAGE_SIZE,
            retstart=retstart,
            WebEnv=web_env,
            query_key=query_key,
        )
        result = Entrez.read(handle)
        handle.close()
        page_pmids = set(result["IdList"])
        before = len(pmids)
        pmids.update(page_pmids)
        print(f"    Page {page}: {len(page_pmids):,} new PMIDs ({len(pmids):,} total)")
        time.sleep(RATE_LIMIT_SEC)
        if not page_pmids:
            break  # safety: empty response means done

    print(f"    Final: {len(pmids):,} unique PMIDs")
    return pmids


# ---------- Stage 2: fetch abstract text via efetch ----------

def fetch_abstracts(pmids: list) -> Iterator[dict]:
    """Fetch full PubMed records for a list of PMIDs in batches.

    Yields one dict per article with extracted fields.
    """
    total = len(pmids)
    for i in range(0, total, EFETCH_BATCH_SIZE):
        batch = pmids[i:i + EFETCH_BATCH_SIZE]
        attempts = 0
        while attempts < 3:
            try:
                handle = Entrez.efetch(
                    db="pubmed",
                    id=",".join(batch),
                    rettype="xml",
                    retmode="xml",
                )
                records = Entrez.read(handle)
                handle.close()
                break
            except Exception as e:
                attempts += 1
                print(f"      efetch attempt {attempts} failed: {e}")
                time.sleep(3)
        else:
            print(f"      WARN: skipping batch {i//EFETCH_BATCH_SIZE+1} after 3 attempts")
            time.sleep(RATE_LIMIT_SEC)
            continue

        for article in records.get("PubmedArticle", []):
            parsed = parse_article(article)
            if parsed:
                yield parsed

        time.sleep(RATE_LIMIT_SEC)
        progress = min(i + EFETCH_BATCH_SIZE, total)
        if progress % 1000 == 0 or progress == total:
            print(f"    Progress: {progress:,}/{total:,} ({progress/total*100:.1f}%)")


def parse_article(article) -> dict | None:
    """Extract structured fields from an Entrez PubmedArticle dict."""
    try:
        medline = article["MedlineCitation"]
        pmid = str(medline["PMID"])

        article_data = medline["Article"]
        title = str(article_data.get("ArticleTitle", "")).strip()

        # Abstract: may be a list of labeled sections
        abstract_parts = []
        abstract_obj = article_data.get("Abstract", {})
        for piece in abstract_obj.get("AbstractText", []):
            text = str(piece).strip()
            label = piece.attributes.get("Label", "") if hasattr(piece, "attributes") else ""
            if label:
                abstract_parts.append(f"{label}: {text}")
            else:
                abstract_parts.append(text)
        abstract = " ".join(abstract_parts).strip()

        # Skip if no abstract (likely indexed without one - filter mentions)
        if not abstract or len(abstract) < 100:
            return None

        # Journal and year
        journal_obj = article_data.get("Journal", {})
        journal_title = str(journal_obj.get("Title", "")).strip()
        year = ""
        pub_date = journal_obj.get("JournalIssue", {}).get("PubDate", {})
        if "Year" in pub_date:
            year = str(pub_date["Year"])
        elif "MedlineDate" in pub_date:
            year = str(pub_date["MedlineDate"])[:4]

        # DOI
        doi = ""
        for aid in article_data.get("ELocationID", []):
            if aid.attributes.get("EIdType") == "doi":
                doi = str(aid)
                break

        # Publication types (Review, Journal Article, etc.)
        pub_types = [str(pt) for pt in article_data.get("PublicationTypeList", [])]

        # MeSH terms
        mesh_terms = []
        for mh in medline.get("MeshHeadingList", []):
            descriptor = mh.get("DescriptorName")
            if descriptor:
                mesh_terms.append(str(descriptor))

        return {
            "pmid": pmid,
            "title": title,
            "abstract": abstract,
            "journal": journal_title,
            "year": year,
            "doi": doi,
            "publication_types": pub_types,
            "mesh_terms": mesh_terms,
        }
    except Exception as e:
        # Don't crash on weird records; just skip them
        pmid = "?"
        try:
            pmid = str(article["MedlineCitation"]["PMID"])
        except Exception:
            pass
        print(f"      Parse error for PMID {pmid}: {e}")
        return None


# ---------- Stage 3: cache load/save with resumability ----------

def load_existing_pmids() -> Set[str]:
    """Load PMIDs already in the cache for resumability."""
    if not OUTPUT.exists():
        return set()
    pmids = set()
    with open(OUTPUT, encoding="utf-8") as f:
        for line in f:
            try:
                pmids.add(json.loads(line)["pmid"])
            except Exception:
                continue
    return pmids


# ---------- Main ----------

def main():
    RAW_PUBMED.mkdir(parents=True, exist_ok=True)

    overall_start = time.time()

    # Check what's already cached
    existing = load_existing_pmids()
    if existing:
        print(f"Resuming: {len(existing):,} PMIDs already cached")

    # Stage 1: collect all PMIDs from all streams
    step("Stage 1: esearch all three streams")
    all_pmids: Set[str] = set()
    per_stream_counts = {}
    for stream in STREAMS:
        pmids = fetch_stream_pmids(stream["id"], stream["query"])
        all_pmids.update(pmids)
        per_stream_counts[stream["id"]] = len(pmids)

    print(f"\n  Per-stream counts:")
    for sid, count in per_stream_counts.items():
        print(f"    {sid}: {count:,}")
    print(f"  Union (deduplicated): {len(all_pmids):,}")

    # Calculate overlap
    union_minus_max = len(all_pmids) - max(per_stream_counts.values())
    overlap = sum(per_stream_counts.values()) - len(all_pmids)
    print(f"  Overlap across streams: {overlap:,}")

    # Stage 2: fetch only PMIDs not already in cache
    to_fetch = sorted(all_pmids - existing)
    print(f"\n  Need to fetch: {len(to_fetch):,} new PMIDs")

    if not to_fetch:
        print("\nNothing new to fetch. Exiting.")
        return

    # Stage 3: efetch and append to cache
    step("Stage 2: efetch full records")
    n_fetched = 0
    n_skipped = 0
    with open(OUTPUT, "a", encoding="utf-8") as f:
        for article in fetch_abstracts(to_fetch):
            f.write(json.dumps(article, ensure_ascii=False) + "\n")
            f.flush()
            n_fetched += 1
    n_skipped = len(to_fetch) - n_fetched

    step("Done")
    print(f"  Fetched and cached: {n_fetched:,}")
    print(f"  Skipped (no abstract / parse error): {n_skipped:,}")
    print(f"  Cache file: {OUTPUT}")
    print(f"  Cache size: {OUTPUT.stat().st_size / 1024 / 1024:.1f} MB")
    print(f"  Total cached now: {len(existing) + n_fetched:,}")
    print(f"\n  Total runtime: {time.time() - overall_start:.1f}s")


if __name__ == "__main__":
    main()
