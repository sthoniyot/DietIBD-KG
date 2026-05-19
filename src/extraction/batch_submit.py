"""Submit a batch of PubMed abstracts to Anthropic's Batch API for triple extraction.

Uses the SAME prompt/tool/validation as src/extraction/llm_extract_production.py
(imports them, no duplication).

Batch API benefits:
- 50% discount vs synchronous calls
- Up to 100,000 requests per batch
- Results within 24 hours (often much faster)

Usage:
    # Test batch first (50 random abstracts, ~$0.25)
    python src/extraction/batch_submit.py --test

    # Full production batch (8,219 abstracts, ~$40-50)
    python src/extraction/batch_submit.py --production

After submission, the batch_id is saved to data/processed/batch_ids.json.
Check status with: python src/extraction/batch_status.py
"""
import argparse
import json
import os
import random
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic
from anthropic.types.messages.batch_create_params import Request

# Import locked production prompt + tool from the validated module
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.extraction.llm_extract_production import (
    SYSTEM_PROMPT, EXTRACTION_TOOL, MODEL, MAX_TOKENS, load_fewshot_examples
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

ABSTRACTS_FILE = PROJECT_ROOT / "data" / "raw" / "pubmed" / "abstracts.jsonl"
BATCH_IDS_FILE = PROJECT_ROOT / "data" / "processed" / "batch_ids.json"
BATCH_REQUESTS_DIR = PROJECT_ROOT / "data" / "processed" / "batch_requests"
BATCH_REQUESTS_DIR.mkdir(exist_ok=True)


def load_abstracts():
    """Load all PubMed abstracts from the Stage 2 corpus."""
    abstracts = []
    with open(ABSTRACTS_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                abstracts.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return abstracts


def build_request(abstract, fewshot_text, custom_id):
    """Build one Anthropic batch request for a single abstract."""
    pmid = abstract["pmid"]
    title = abstract.get("title", "")
    abstract_text = abstract.get("abstract", "")

    user_content = f"""Here are example abstracts and the correct extractions:

{fewshot_text}

---

Now extract from this abstract:

PMID: {pmid}
Title: {title}
Abstract: {abstract_text[:5000]}

Before calling submit_triples:
1. Check: is this a review or off-scope paper? If so, return empty array.
2. For each triple, verify (subject_type, predicate, object_type) matches the schema.
3. Check directionality: did you infer Microbe-Disease from intervention effect? Drop those.
4. Check list-splitting: did you split a single list of taxa? Keep only 1-2 most emphasized.

Call submit_triples now."""

    return Request(
        custom_id=custom_id,
        params={
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "system": SYSTEM_PROMPT,
            "tools": [EXTRACTION_TOOL],
            "tool_choice": {"type": "tool", "name": "submit_triples"},
            "messages": [{"role": "user", "content": user_content}],
        }
    )


def save_batch_record(batch_id, batch_type, n_requests, request_ids):
    """Save batch metadata for status checking and result processing."""
    record = {
        "batch_id": batch_id,
        "batch_type": batch_type,
        "n_requests": n_requests,
        "submitted_at": datetime.utcnow().isoformat() + "Z",
        "request_ids_file": str(BATCH_REQUESTS_DIR / f"{batch_id}_requests.json"),
    }

    # Save request_ids (so we can map results back to PMIDs)
    with open(record["request_ids_file"], "w") as f:
        json.dump(request_ids, f, indent=2)

    # Append to batch_ids.json
    if BATCH_IDS_FILE.exists():
        with open(BATCH_IDS_FILE) as f:
            batches = json.load(f)
    else:
        batches = []

    batches.append(record)
    with open(BATCH_IDS_FILE, "w") as f:
        json.dump(batches, f, indent=2)

    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true",
                        help="Submit 50-abstract test batch")
    parser.add_argument("--production", action="store_true",
                        help="Submit full production batch (8,219 abstracts)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Build requests but don't submit")
    parser.add_argument("--cost-cap", type=float, default=75.0,
                        help="Hard cost cap in USD (default 75)")
    args = parser.parse_args()

    if not (args.test or args.production):
        sys.exit("ERROR: specify --test or --production")
    if args.test and args.production:
        sys.exit("ERROR: --test and --production are mutually exclusive")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ERROR: ANTHROPIC_API_KEY not set in .env")
    client = Anthropic(api_key=api_key)

    print(f"Loading abstracts from {ABSTRACTS_FILE}...")
    all_abstracts = load_abstracts()
    print(f"  {len(all_abstracts):,} abstracts in corpus")

    # Select which abstracts to process
    if args.test:
        random.seed(42)
        shuffled = sorted(all_abstracts, key=lambda x: x["pmid"])
        random.shuffle(shuffled)
        abstracts_to_send = shuffled[:50]
        batch_type = "test"
        print(f"  TEST mode: 50 random abstracts selected")
    else:
        abstracts_to_send = all_abstracts
        batch_type = "production"
        print(f"  PRODUCTION mode: all {len(abstracts_to_send):,} abstracts")

    # Build fewshot examples (same as production script)
    print(f"\nLoading few-shot examples...")
    fewshot_text = load_fewshot_examples()
    print(f"  Few-shot text: {len(fewshot_text):,} chars")

    # Build batch requests
    print(f"\nBuilding {len(abstracts_to_send):,} batch requests...")
    requests = []
    request_ids = {}  # custom_id -> pmid
    for abs_data in abstracts_to_send:
        custom_id = f"pmid_{abs_data['pmid']}"
        request = build_request(abs_data, fewshot_text, custom_id)
        requests.append(request)
        request_ids[custom_id] = abs_data["pmid"]

    # Cost estimate
    # Each request: ~7000 input tokens, ~400 output tokens (from Stage 4 data)
    # Batch pricing: 50% off standard ($1/MTok input, $5/MTok output)
    est_input_per_request = 7000
    est_output_per_request = 400
    total_input = est_input_per_request * len(requests)
    total_output = est_output_per_request * len(requests)
    est_cost = (total_input / 1_000_000 * 1.00 * 0.5 +
                total_output / 1_000_000 * 5.00 * 0.5)
    print(f"\nEstimated cost: ${est_cost:.2f}")
    print(f"  Input tokens (est):  {total_input:,}")
    print(f"  Output tokens (est): {total_output:,}")

    if est_cost > args.cost_cap:
        sys.exit(f"ERROR: estimated cost ${est_cost:.2f} exceeds cap ${args.cost_cap:.2f}")

    if args.dry_run:
        print("\nDRY RUN: not submitting. Exit.")
        return

    # Confirm before submission
    print(f"\nReady to submit {batch_type} batch.")
    response = input(f"Submit batch? [yes/N]: ").strip().lower()
    if response != "yes":
        print("Aborted.")
        return

    # Submit
    print(f"\nSubmitting batch to Anthropic...")
    batch_response = client.messages.batches.create(requests=requests)
    batch_id = batch_response.id
    print(f"  Batch ID:    {batch_id}")
    print(f"  Status:      {batch_response.processing_status}")
    print(f"  Created at:  {batch_response.created_at}")
    print(f"  Expires at:  {batch_response.expires_at}")

    # Save record
    record = save_batch_record(batch_id, batch_type, len(requests), request_ids)
    print(f"\nBatch record saved to: {BATCH_IDS_FILE}")
    print(f"Request ID mapping at: {record['request_ids_file']}")

    print(f"\n=== Next Steps ===")
    print(f"1. Check status: python src/extraction/batch_status.py")
    print(f"2. When complete: python src/extraction/batch_process.py --batch-id {batch_id}")
    print(f"\nBatch typically completes within 1-12 hours.")


if __name__ == "__main__":
    main()
