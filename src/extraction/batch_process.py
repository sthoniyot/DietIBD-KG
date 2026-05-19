"""Process completed Anthropic batch results into a TSV of extracted triples.

Reads the results JSONL from the batch API, parses tool-use outputs,
applies post-validation (schema enforcement), and writes triples to
data/processed/llm_extractions/extractions_production_BATCHID.tsv

Usage:
    python src/extraction/batch_process.py --batch-id BATCH_ID
"""
import argparse
import csv
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from src.extraction.llm_extract_production import validate_triple, PREDICATE_TYPES

BATCH_IDS_FILE = PROJECT_ROOT / "data" / "processed" / "batch_ids.json"
EXTRACTIONS_DIR = PROJECT_ROOT / "data" / "processed" / "llm_extractions"
EXTRACTIONS_DIR.mkdir(exist_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-id", required=True)
    args = parser.parse_args()

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ERROR: ANTHROPIC_API_KEY not set")
    client = Anthropic(api_key=api_key)

    # Find batch record
    with open(BATCH_IDS_FILE) as f:
        records = json.load(f)
    record = next((r for r in records if r["batch_id"] == args.batch_id), None)
    if not record:
        sys.exit(f"Batch {args.batch_id} not in records")

    # Check batch is done
    batch = client.messages.batches.retrieve(args.batch_id)
    if batch.processing_status != "ended":
        sys.exit(f"Batch not complete yet (status: {batch.processing_status})")

    print(f"Processing batch: {args.batch_id}")
    print(f"  Type: {record['batch_type']}")
    print(f"  Requests: {record['n_requests']}")

    # Stream results from the API
    print(f"\nStreaming results...")
    results = list(client.messages.batches.results(args.batch_id))
    print(f"  {len(results)} results received")

    # Parse each result
    all_rows = []
    n_success = 0
    n_errored = 0
    n_dropped_schema = 0
    n_total_triples = 0

    for result in results:
        custom_id = result.custom_id
        pmid = custom_id.replace("pmid_", "")

        if result.result.type != "succeeded":
            n_errored += 1
            all_rows.append({
                "pmid": pmid, "triple_id": "ERROR",
                "subject_name": "-", "subject_type": "-",
                "predicate": "ERROR", "object_name": "-", "object_type": "-",
                "evidence_span": f"Batch error: {result.result.type}",
                "evidence_type": "-", "confidence": 0,
                "notes": f"Error type: {result.result.type}",
            })
            continue

        n_success += 1
        message = result.result.message

        # Find the tool_use block
        triples = []
        for block in message.content:
            if block.type == "tool_use" and block.name == "submit_triples":
                triples = block.input.get("triples", [])
                break

        # Post-validate each triple
        valid_triples = []
        for t in triples:
            if validate_triple(t):
                valid_triples.append(t)
            else:
                n_dropped_schema += 1

        n_total_triples += len(valid_triples)

        if not valid_triples:
            all_rows.append({
                "pmid": pmid, "triple_id": "T0",
                "subject_name": "-", "subject_type": "-",
                "predicate": "NONE", "object_name": "-", "object_type": "-",
                "evidence_span": "-", "evidence_type": "-",
                "confidence": 0, "notes": "Empty extraction or all schema-violating",
            })
        else:
            for tid, t in enumerate(valid_triples, 1):
                all_rows.append({"pmid": pmid, "triple_id": f"T{tid}", **t})

    # Write output
    out_path = EXTRACTIONS_DIR / f"extractions_production_{args.batch_id}.tsv"
    cols = ["pmid", "triple_id", "subject_name", "subject_type", "predicate",
            "object_name", "object_type", "evidence_span", "evidence_type",
            "confidence", "notes"]

    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=cols, delimiter="\t",
                                quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for r in all_rows:
            writer.writerow({c: r.get(c, "") for c in cols})

    print(f"\n=== Summary ===")
    print(f"  Total results:       {len(results)}")
    print(f"  Successful:          {n_success}")
    print(f"  Errored:             {n_errored}")
    print(f"  Schema-dropped:      {n_dropped_schema}")
    print(f"  Valid triples kept:  {n_total_triples}")
    print(f"  Avg/abstract:        {n_total_triples / max(n_success, 1):.2f}")
    print(f"\nOutput: {out_path}")
    print(f"\nUsage stats from API:")
    print(f"  Input tokens:  {batch.request_counts.succeeded:,} requests succeeded")


if __name__ == "__main__":
    main()
