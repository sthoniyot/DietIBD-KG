"""Retry abstracts that errored in a previous batch submission.

Reads the production batch TSV, finds rows with predicate='ERROR',
extracts those PMIDs, and submits a new batch with just those abstracts.

Usage:
    python src/extraction/batch_retry_errors.py \\
        --input data/processed/llm_extractions/extractions_production_*.tsv
"""
import argparse
import csv
import glob
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic
from anthropic.types.messages.batch_create_params import Request

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from src.extraction.llm_extract_production import (
    SYSTEM_PROMPT, EXTRACTION_TOOL, MODEL, MAX_TOKENS, load_fewshot_examples
)
from src.extraction.batch_submit import build_request, save_batch_record

ABSTRACTS_FILE = PROJECT_ROOT / "data" / "raw" / "pubmed" / "abstracts.jsonl"
BATCH_IDS_FILE = PROJECT_ROOT / "data" / "processed" / "batch_ids.json"


def load_errored_pmids(tsv_path):
    pmids = []
    with open(tsv_path, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if r["predicate"] == "ERROR":
                pmids.append(r["pmid"])
    return pmids


def load_abstract_lookup():
    """Build PMID -> abstract dict."""
    lookup = {}
    with open(ABSTRACTS_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                art = json.loads(line)
                lookup[art["pmid"]] = art
            except json.JSONDecodeError:
                pass
    return lookup


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--cost-cap", type=float, default=5.0)
    args = parser.parse_args()

    input_files = sorted(glob.glob(args.input)) if "*" in args.input else [args.input]
    if not input_files:
        sys.exit(f"ERROR: no files matched {args.input}")
    tsv_path = input_files[-1]

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ERROR: ANTHROPIC_API_KEY not set")
    client = Anthropic(api_key=api_key)

    print(f"Reading errored PMIDs from {tsv_path}...")
    errored_pmids = load_errored_pmids(tsv_path)
    print(f"  {len(errored_pmids)} PMIDs to retry")

    if not errored_pmids:
        sys.exit("No errored PMIDs found. Nothing to retry.")

    print(f"\nLoading abstract corpus...")
    abstract_lookup = load_abstract_lookup()
    print(f"  {len(abstract_lookup):,} abstracts indexed")

    # Build retry payload
    abstracts_to_retry = []
    missing_in_corpus = []
    for pmid in errored_pmids:
        if pmid in abstract_lookup:
            abstracts_to_retry.append(abstract_lookup[pmid])
        else:
            missing_in_corpus.append(pmid)

    print(f"\n  {len(abstracts_to_retry)} abstracts ready to retry")
    if missing_in_corpus:
        print(f"  {len(missing_in_corpus)} PMIDs missing from corpus (can't retry)")

    print(f"\nLoading few-shot examples...")
    fewshot_text = load_fewshot_examples()

    print(f"\nBuilding requests...")
    requests = []
    request_ids = {}
    for abs_data in abstracts_to_retry:
        custom_id = f"pmid_{abs_data['pmid']}"
        requests.append(build_request(abs_data, fewshot_text, custom_id))
        request_ids[custom_id] = abs_data["pmid"]

    # Cost estimate
    est_cost = len(requests) * 0.005  # ~$0.005/abstract with batch discount
    print(f"\nEstimated cost: ${est_cost:.2f}")
    if est_cost > args.cost_cap:
        sys.exit(f"ERROR: cost ${est_cost:.2f} exceeds cap ${args.cost_cap:.2f}")

    response = input(f"\nSubmit retry batch ({len(requests)} requests)? [yes/N]: ").strip().lower()
    if response != "yes":
        print("Aborted.")
        return

    print(f"\nSubmitting...")
    batch_response = client.messages.batches.create(requests=requests)
    batch_id = batch_response.id
    print(f"  Batch ID: {batch_id}")
    print(f"  Status:   {batch_response.processing_status}")

    save_batch_record(batch_id, "retry_errors", len(requests), request_ids)
    print(f"\n=== Next Steps ===")
    print(f"1. Check status: python src/extraction/batch_status.py")
    print(f"2. When done:    python src/extraction/batch_process.py --batch-id {batch_id}")


if __name__ == "__main__":
    main()
