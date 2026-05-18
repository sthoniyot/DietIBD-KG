"""LLM extraction v2 - tightened prompt + post-validation.

Changes vs v1:
- Explicit OFF-SCOPE list (antibiotics, drugs, surgical, materials science)
- Explicit INCLUDE rule (DSS mouse + dietary compounds)
- Post-validation: drop triples where (subject_type, object_type) doesn't match predicate's required combination

Run:
    python src/extraction/llm_extract_v2.py --split dev --version v2
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

MODEL = "claude-haiku-4-5-20251001"
MAX_RETRIES = 3
MAX_TOKENS = 2048

PREDICATES = [
    "contains", "produces", "increases_abundance_of", "decreases_abundance_of",
    "increased_in", "decreased_in", "increases_marker", "decreases_marker",
    "has_high_FODMAP_content_of",
]
ENTITY_TYPES = ["Food", "Bioactive", "Microbe", "IBD_Outcome", "Pathway"]
EVIDENCE_TYPES = ["rct", "cohort", "case_control", "animal",
                  "mechanistic", "review", "meta_analysis"]

# Predicate type constraints for post-validation
PREDICATE_TYPES = {
    "contains": ("Food", "Bioactive"),
    "produces": ("Microbe", "Bioactive"),
    "increases_abundance_of": ("Food", "Microbe"),
    "decreases_abundance_of": ("Food", "Microbe"),
    "increased_in": ("Microbe", "IBD_Outcome"),
    "decreased_in": ("Microbe", "IBD_Outcome"),
    "increases_marker": ("Food", "IBD_Outcome"),
    "decreases_marker": ("Food", "IBD_Outcome"),
    "has_high_FODMAP_content_of": ("Food", "Bioactive"),
}

EXTRACTION_TOOL = {
    "name": "submit_triples",
    "description": "Submit extracted triples. Empty array if no extractable claims.",
    "input_schema": {
        "type": "object",
        "properties": {
            "triples": {
                "type": "array",
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

# ALLOWED PREDICATES (only these 9):

| Predicate                       | Subject TYPE | Object TYPE   |
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

**CRITICAL: subject_type and object_type MUST match the predicate. Before submitting, verify:**
- `decreased_in` and `increased_in`: subject is ALWAYS Microbe, object is ALWAYS IBD_Outcome. NEVER swap.
- `produces`: subject is ALWAYS Microbe, object is ALWAYS Bioactive (a metabolite).
- `*_marker`: subject is ALWAYS Food, object is ALWAYS IBD_Outcome.

# OFF-SCOPE PAPERS (return empty triples array):

These topics are NOT in scope - if the paper is primarily about:
- **Antibiotic interventions** (vancomycin, mesalazine, sulfasalazine, neomycin, rifaximin, etc.) — even if they modulate microbiome
- **Drug pharmacokinetics or non-dietary drug efficacy** (Anti-TNF, JAK inhibitors, biologics)
- **Surgical or procedural interventions** (colonoscopy, endoscopy, surgery, moxibustion, acupuncture)
- **Materials science / drug delivery** (nanoparticles, hydrogels, barrier devices, capsules)
- **Bioengineered diagnostics** (calprotectin biosensors, engineered probiotic biosensors)
- **Cancer surveillance** (chromoendoscopy, dysplasia screening, neoplasia)
- **Clinical surveys** (probiotic prescription patterns, classification agreement)
- **Pure immunology** focused on signaling (NF-kB, TLR4, MAPK, AKT, Nrf2, Th17/Treg cells) without food/microbe data
- **Cytokine relationships** (TNF-α, IL-6, IL-10 etc. as subject or object) — schema does not include Cytokine entity

For these papers, return {"triples": []}. Do NOT extract microbiome findings that are byproducts of the off-scope intervention.

**Example: A paper says "vancomycin treatment reduced Faecalibacterium in CD patients."** Do NOT extract `Faecalibacterium decreased_in CD` — this is an antibiotic effect, not a natural disease finding.

# IN-SCOPE PAPERS (extract triples):

These topics ARE in scope - extract carefully:
- **DSS-induced mouse colitis** with dietary compound treatment (polyphenols, polysaccharides, oligosaccharides, peptides, plant extracts, vitamins, fatty acids, amino acids). The compound is `Food` (per supplement-as-Food convention).
- **TNBS or DNBS colitis** mouse models with dietary intervention.
- **Human cohort or RCT studies** of dietary patterns, fiber intake, FODMAP, specific foods.
- **Microbiome composition studies** in IBD patients (no drug intervention): increased_in / decreased_in
- **Microbial metabolism studies**: Microbe `produces` Bioactive (butyrate, SCFA, indole, etc.)
- **Food composition studies**: Food `contains` Bioactive.

# EXTRACTION RULES:

1. **evidence_span MUST be verbatim** - copy exact text from abstract, character for character. Do not paraphrase or add parentheticals.

2. **Hedged claims** ("may", "could", "warrants"): include but lower confidence to 0.60-0.70.

3. **Use specific entity names from the abstract** - "F. prausnitzii" → "Faecalibacterium prausnitzii", "TH-GLs" → "tilapia head glycolipids", "rice protein" not "fibre".

4. **Compounds-as-Food convention**: A bioactive compound (resveratrol, curcumin, quercetin, butyrate, polysaccharide, peptide) administered as a dietary intervention is typed as `Food`, not `Bioactive`.

5. **evidence_type**:
   - `rct`: randomized human trial
   - `cohort`: observational human study
   - `case_control`: case-control human study
   - `animal`: any animal model (DSS mice, TNBS, etc.)
   - `mechanistic`: in vitro, cell culture, isolated strains
   - `review`: review article
   - `meta_analysis`: systematic review/meta-analysis

6. **confidence**:
   - 0.85-0.90: Strong human cohort/RCT with sample size
   - 0.75-0.80: Animal study with mechanism / p-value
   - 0.70: Direct animal evidence
   - 0.65: Hedged claims, indirect inference, review-derived
   - 0.60: Very weak evidence (mostly skip)

7. **When in doubt, SKIP.** False positives hurt precision more than false negatives hurt recall.

You MUST call the submit_triples tool to submit your extractions."""


def format_fewshot_example(annot_id, pmid, title, abstract, triples):
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
        parts.append('submit_triples({"triples": []})')
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
        parts.append("submit_triples(")
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
        "annot_id": aid, "pmid": source[aid]["pmid"],
        "title": source[aid]["title"], "abstract": source[aid]["abstract"],
    } for aid in split_ids]
    if limit:
        abstracts = abstracts[:limit]
    return abstracts


def validate_triple(t):
    """Return True if triple's (subject_type, object_type) matches predicate."""
    expected = PREDICATE_TYPES.get(t.get("predicate"))
    if not expected:
        return False
    return (t.get("subject_type"), t.get("object_type")) == expected


def extract_one(client, abstract_data, fewshot_text):
    user_content = f"""Here are example abstracts and the correct extractions:

{fewshot_text}

---

Now extract triples from this abstract using the submit_triples tool:

PMID: {abstract_data["pmid"]}
Title: {abstract_data["title"]}
Abstract: {abstract_data["abstract"][:5000]}

Before calling submit_triples, verify for each triple that the (subject_type, predicate, object_type) combination matches the table in the system prompt.

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
            raise RuntimeError("No tool_use block")
        except Exception as e:
            last_err = e
            print(f"      attempt {attempt+1} failed: {type(e).__name__}: {e}")
            time.sleep(2 ** attempt)
    return [], None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "test", "fewshot"], required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ERROR: ANTHROPIC_API_KEY not set")
    client = Anthropic(api_key=api_key)

    print(f"Loading few-shot examples...")
    fewshot_text = load_fewshot_examples()
    print(f"  {len(fewshot_text):,} chars")

    abstracts = load_split_abstracts(args.split, args.limit)
    print(f"\n{len(abstracts)} abstracts to extract")

    output_path = EXTRACTIONS_DIR / f"extractions_{args.split}_{args.version}.tsv"
    print(f"Output: {output_path}\n")

    total_in = 0; total_out = 0; total_triples = 0; total_dropped = 0
    rows = []

    for i, abs_data in enumerate(abstracts, 1):
        print(f"  [{i:>3}/{len(abstracts)}] {abs_data['annot_id']}...", end=" ", flush=True)
        triples, usage = extract_one(client, abs_data, fewshot_text)
        if usage:
            total_in += usage["input_tokens"]
            total_out += usage["output_tokens"]

        # Post-validation: drop schema-violating triples
        valid_triples = []
        dropped = []
        for t in triples:
            if validate_triple(t):
                valid_triples.append(t)
            else:
                dropped.append(t)
        total_dropped += len(dropped)
        total_triples += len(valid_triples)

        msg = f"{len(valid_triples)} kept"
        if dropped:
            msg += f" ({len(dropped)} dropped: schema violation)"
        print(msg)

        for tid, t in enumerate(valid_triples, 1):
            rows.append({"annot_id": abs_data["annot_id"], "pmid": abs_data["pmid"],
                         "triple_id": f"T{tid}", **t})
        if not valid_triples:
            rows.append({
                "annot_id": abs_data["annot_id"], "pmid": abs_data["pmid"],
                "triple_id": "T0", "subject_name": "-", "subject_type": "-",
                "predicate": "NONE", "object_name": "-", "object_type": "-",
                "evidence_span": "-", "evidence_type": "-",
                "confidence": 0, "notes": "LLM returned empty or all dropped",
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

    cost = total_in / 1_000_000 * 1.00 + total_out / 1_000_000 * 5.00
    print(f"\n=== Summary ===")
    print(f"  Abstracts:           {len(abstracts)}")
    print(f"  Triples kept:        {total_triples}")
    print(f"  Triples dropped:     {total_dropped}")
    print(f"  Avg kept/abstract:   {total_triples/len(abstracts):.2f}")
    print(f"  Input tokens:        {total_in:,}")
    print(f"  Output tokens:       {total_out:,}")
    print(f"  Cost:                ${cost:.4f}")


if __name__ == "__main__":
    main()
