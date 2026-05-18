"""LLM-based triple extraction from PubMed abstracts using Anthropic Claude.

Uses Claude Haiku 4.5 with tool-use forced for structured outputs.
Few-shot examples loaded from gold_split_fewshot.tsv at runtime.

Usage:
    # Test on 3 abstracts (sanity check, ~$0.05)
    python src/extraction/llm_extract.py --split dev --version v1_test --limit 3

    # Full dev set extraction (~$0.30)
    python src/extraction/llm_extract.py --split dev --version v1

    # Test set extraction (only after prompt locked)
    python src/extraction/llm_extract.py --split test --version final
"""
import argparse
import csv
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

PROCESSED = PROJECT_ROOT / "data" / "processed"
EXTRACTIONS_DIR = PROCESSED / "llm_extractions"
EXTRACTIONS_DIR.mkdir(exist_ok=True)

# Claude Haiku 4.5 - fast and cheap, comparable to GPT-4o-mini for IE
MODEL = "claude-haiku-4-5-20251001"
MAX_RETRIES = 3
MAX_TOKENS = 2048

# Schema vocabulary
PREDICATES = [
    "contains", "produces", "increases_abundance_of", "decreases_abundance_of",
    "increased_in", "decreased_in", "increases_marker", "decreases_marker",
    "has_high_FODMAP_content_of",
]
ENTITY_TYPES = ["Food", "Bioactive", "Microbe", "IBD_Outcome", "Pathway"]
EVIDENCE_TYPES = ["rct", "cohort", "case_control", "animal",
                  "mechanistic", "review", "meta_analysis"]

# Claude tool schema (Claude uses tool-use for structured outputs)
EXTRACTION_TOOL = {
    "name": "submit_triples",
    "description": "Submit extracted triples from the abstract. Use empty array if no extractable claims.",
    "input_schema": {
        "type": "object",
        "properties": {
            "triples": {
                "type": "array",
                "description": "Array of extracted triples. Empty array if no extractable claims.",
                "items": {
                    "type": "object",
                    "properties": {
                        "subject_name": {"type": "string"},
                        "subject_type": {"type": "string", "enum": ENTITY_TYPES},
                        "predicate":    {"type": "string", "enum": PREDICATES},
                        "object_name":  {"type": "string"},
                        "object_type":  {"type": "string", "enum": ENTITY_TYPES},
                        "evidence_span": {"type": "string"},
                        "evidence_type": {"type": "string", "enum": EVIDENCE_TYPES},
                        "confidence":   {"type": "number"},
                        "notes":        {"type": "string"},
                    },
                    "required": ["subject_name", "subject_type", "predicate",
                                 "object_name", "object_type", "evidence_span",
                                 "evidence_type", "confidence", "notes"],
                }
            }
        },
        "required": ["triples"],
    }
}

SYSTEM_PROMPT = """You are a biomedical knowledge graph extractor for diet-microbiome-IBD relationships.

Read each PubMed abstract and extract structured triples matching this STRICT schema.

ALLOWED PREDICATES (only these 9, with required entity types):

| Predicate                       | Subject Type | Object Type   |
|---------------------------------|--------------|---------------|
| contains                        | Food         | Bioactive     |
| produces                        | Microbe      | Bioactive     |
| increases_abundance_of          | Food         | Microbe       |
| decreases_abundance_of          | Food         | Microbe       |
| increased_in                    | Microbe      | IBD_Outcome   |
| decreased_in                    | Microbe      | IBD_Outcome   |
| increases_marker                | Food         | IBD_Outcome   |
| decreases_marker                | Food         | IBD_Outcome   |
| has_high_FODMAP_content_of      | Food         | Bioactive     |

RULES:

1. If the abstract has NO extractable definitive claim matching this schema, submit an empty triples array.

2. Reviews, methodology papers, off-scope papers (cancer surveillance, drug pharmacokinetics, surgery, materials science): submit empty array.

3. evidence_span MUST be verbatim. Copy exact text from the abstract, character for character. Do NOT paraphrase, summarize, or add parentheticals.

4. Hedged claims ("may", "could", "warrants"): include but lower confidence to 0.60-0.70.

5. If a claim doesn't fit a predicate (Microbe-as-treatment, Bioactive→IBD_Outcome, Cytokine/signaling like NF-kB/TLR4/MAPK/AKT/Th17/Treg): SKIP it. Do not force-fit.

6. evidence_type values: rct (randomized trial), cohort (observational human), case_control, animal (any animal model including DSS mice), mechanistic (in vitro, cell culture), review, meta_analysis.

7. Confidence calibration:
   - 0.85-0.90: Strong human cohort/RCT with sample size
   - 0.75-0.80: Animal study with mechanism/p-value
   - 0.70: Direct animal evidence
   - 0.65: Hedged claims, indirect inference, review-derived
   - 0.60: Very weak (mostly skip)

8. Use specific entity names from the abstract. Don't generalize ("F. prausnitzii" → "Faecalibacterium prausnitzii", "rice protein" → "rice protein" not "fibre").

9. Compounds administered as dietary supplements (resveratrol, curcumin, quercetin, butyrate, phosvitin, polysaccharides) → type as Food when the evidence treats them as the dietary intervention.

CRITICAL: Be conservative. False positives (extracting wrong triples) are worse than false negatives (missing some). When in doubt, skip.

You MUST call the submit_triples tool to submit your extractions."""


def format_fewshot_example(annot_id, pmid, title, abstract, triples):
    """Format one few-shot example showing input + expected output."""
    parts = [
        f"<example>",
        f"<input>",
        f"PMID: {pmid}",
        f"Title: {title}",
        f"Abstract: {abstract[:1500]}",
        f"</input>",
        f"<output>",
    ]

    if not triples or all(t["predicate"] == "NONE" for t in triples):
        parts.append('Tool call: submit_triples({"triples": []})')
        parts.append("(Off-scope or no extractable claims.)")
    else:
        json_triples = []
        for t in triples:
            if t["predicate"] == "NONE":
                continue
            try:
                conf = float(t["your_confidence"])
            except (ValueError, TypeError):
                conf = 0.70
            json_triples.append({
                "subject_name": t["subject_name"],
                "subject_type": t["subject_type"],
                "predicate": t["predicate"],
                "object_name": t["object_name"],
                "object_type": t["object_type"],
                "evidence_span": t["evidence_span"],
                "evidence_type": t["evidence_type"],
                "confidence": conf,
                "notes": t.get("notes", ""),
            })
        parts.append('Tool call: submit_triples(')
        parts.append(json.dumps({"triples": json_triples}, indent=2))
        parts.append(')')

    parts.append('</output>')
    parts.append('</example>')
    return "\n".join(parts)


def load_fewshot_examples():
    with open(PROCESSED / "gold_split_fewshot.tsv", encoding="utf-8") as f:
        fewshot_rows = list(csv.DictReader(f, delimiter="\t"))

    with open(PROCESSED / "gold_standard_to_annotate.tsv", encoding="utf-8") as f:
        source = {r["annot_id"]: r for r in csv.DictReader(f, delimiter="\t")}

    by_aid = defaultdict(list)
    for r in fewshot_rows:
        by_aid[r["annot_id"]].append(r)

    examples = []
    for aid in sorted(by_aid):
        src = source[aid]
        examples.append(format_fewshot_example(
            aid, src["pmid"], src["title"], src["abstract"], by_aid[aid]
        ))
    return "\n\n".join(examples)


def load_split_abstracts(split_name, limit=None):
    split_path = PROCESSED / f"gold_split_{split_name}.tsv"
    with open(split_path, encoding="utf-8") as f:
        split_rows = list(csv.DictReader(f, delimiter="\t"))
    split_ids = sorted(set(r["annot_id"] for r in split_rows))

    with open(PROCESSED / "gold_standard_to_annotate.tsv", encoding="utf-8") as f:
        source = {r["annot_id"]: r for r in csv.DictReader(f, delimiter="\t")}

    abstracts = [{
        "annot_id": aid,
        "pmid": source[aid]["pmid"],
        "title": source[aid]["title"],
        "abstract": source[aid]["abstract"],
    } for aid in split_ids]

    if limit:
        abstracts = abstracts[:limit]
    return abstracts


def extract_one(client, abstract_data, fewshot_text):
    """Extract triples for one abstract. Returns (triples_list, usage_dict)."""
    user_content = f"""Here are example abstracts and the correct extractions:

{fewshot_text}

---

Now extract triples from this abstract using the submit_triples tool:

PMID: {abstract_data["pmid"]}
Title: {abstract_data["title"]}
Abstract: {abstract_data["abstract"][:5000]}

Call submit_triples now."""

    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=[EXTRACTION_TOOL],
                tool_choice={"type": "tool", "name": "submit_triples"},
                messages=[{"role": "user", "content": user_content}],
            )

            for block in response.content:
                if block.type == "tool_use" and block.name == "submit_triples":
                    triples = block.input.get("triples", [])
                    usage = {
                        "input_tokens": response.usage.input_tokens,
                        "output_tokens": response.usage.output_tokens,
                    }
                    return triples, usage

            raise RuntimeError("No tool_use block in response")
        except Exception as e:
            last_err = e
            print(f"      attempt {attempt+1} failed: {type(e).__name__}: {e}")
            time.sleep(2 ** attempt)

    print(f"      FAILED after {MAX_RETRIES} attempts: {last_err}")
    return [], None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "test", "fewshot"], required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ERROR: ANTHROPIC_API_KEY not set in .env")

    client = Anthropic(api_key=api_key)

    print(f"Loading few-shot examples...")
    fewshot_text = load_fewshot_examples()
    print(f"  Few-shot text: {len(fewshot_text):,} chars")

    print(f"\nLoading {args.split} abstracts...")
    abstracts = load_split_abstracts(args.split, args.limit)
    print(f"  {len(abstracts)} abstracts to extract")

    output_path = EXTRACTIONS_DIR / f"extractions_{args.split}_{args.version}.tsv"
    print(f"\nExtracting using {MODEL}... (output: {output_path})")

    total_in = 0
    total_out = 0
    total_triples = 0
    rows = []

    for i, abs_data in enumerate(abstracts, 1):
        print(f"  [{i:>3}/{len(abstracts)}] {abs_data['annot_id']} (PMID {abs_data['pmid']})...", end=" ", flush=True)
        triples, usage = extract_one(client, abs_data, fewshot_text)

        if usage:
            total_in += usage["input_tokens"]
            total_out += usage["output_tokens"]

        total_triples += len(triples)
        print(f"{len(triples)} triples")

        for tid, t in enumerate(triples, 1):
            row = {
                "annot_id": abs_data["annot_id"],
                "pmid": abs_data["pmid"],
                "triple_id": f"T{tid}",
                **t,
            }
            rows.append(row)

        if not triples:
            rows.append({
                "annot_id": abs_data["annot_id"],
                "pmid": abs_data["pmid"],
                "triple_id": "T0",
                "subject_name": "-", "subject_type": "-",
                "predicate": "NONE",
                "object_name": "-", "object_type": "-",
                "evidence_span": "-", "evidence_type": "-",
                "confidence": 0, "notes": "LLM returned empty extraction",
            })

    cols = ["annot_id", "pmid", "triple_id", "subject_name", "subject_type",
            "predicate", "object_name", "object_type", "evidence_span",
            "evidence_type", "confidence", "notes"]
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=cols, delimiter="\t",
                                quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for r in rows:
            writer.writerow({c: r.get(c, "") for c in cols})

    # Claude Haiku 4.5 pricing (as of late 2025): $1.00/MTok input, $5.00/MTok output
    cost = total_in / 1_000_000 * 1.00 + total_out / 1_000_000 * 5.00

    print(f"\n=== Summary ===")
    print(f"  Abstracts processed: {len(abstracts)}")
    print(f"  Triples extracted:   {total_triples}")
    print(f"  Avg/abstract:        {total_triples/len(abstracts):.2f}")
    print(f"  Input tokens:        {total_in:,}")
    print(f"  Output tokens:       {total_out:,}")
    print(f"  Estimated cost:      ${cost:.4f}")
    print(f"  Output file:         {output_path}")


if __name__ == "__main__":
    main()
