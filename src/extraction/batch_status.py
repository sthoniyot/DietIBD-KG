"""Check the status of submitted Anthropic batch jobs.

Reads batch IDs from data/processed/batch_ids.json and queries the API
for each one's current state.

Usage:
    python src/extraction/batch_status.py              # all batches
    python src/extraction/batch_status.py --batch-id BATCH_ID  # one batch
"""
import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")
BATCH_IDS_FILE = PROJECT_ROOT / "data" / "processed" / "batch_ids.json"


def format_status(batch):
    """Return human-readable status string."""
    status = batch.processing_status
    counts = batch.request_counts
    total = counts.processing + counts.succeeded + counts.errored + counts.canceled + counts.expired
    if total == 0:
        return f"{status:<12} (counts not yet available)"

    pct_done = (counts.succeeded + counts.errored) / total * 100
    return (f"{status:<12} | "
            f"succeeded: {counts.succeeded:>5} | "
            f"errored: {counts.errored:>4} | "
            f"processing: {counts.processing:>5} | "
            f"{pct_done:5.1f}% complete")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-id", help="Check only this specific batch")
    args = parser.parse_args()

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ERROR: ANTHROPIC_API_KEY not set")
    client = Anthropic(api_key=api_key)

    if not BATCH_IDS_FILE.exists():
        sys.exit("No batches submitted yet (data/processed/batch_ids.json missing)")

    with open(BATCH_IDS_FILE) as f:
        records = json.load(f)

    if args.batch_id:
        records = [r for r in records if r["batch_id"] == args.batch_id]
        if not records:
            sys.exit(f"Batch {args.batch_id} not found in records")

    print(f"Checking {len(records)} batch(es):\n")
    for record in records:
        batch_id = record["batch_id"]
        try:
            batch = client.messages.batches.retrieve(batch_id)
        except Exception as e:
            print(f"  {batch_id[:30]}... ERROR: {e}")
            continue

        print(f"  Batch: {batch_id}")
        print(f"  Type:  {record['batch_type']}")
        print(f"  Reqs:  {record['n_requests']}")
        print(f"  Subm:  {record['submitted_at']}")
        print(f"  State: {format_status(batch)}")
        if batch.processing_status == "ended":
            print(f"  Results URL: available - run batch_process.py")
        print()


if __name__ == "__main__":
    main()
