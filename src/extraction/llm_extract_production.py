"""LLM extraction v3 - precision-focused refinement of v2.

Changes from v2:
- Anti-list-splitting: don't split "taxa A, B, C all elevated" into 3 triples
- Directionality clarification: don't infer Microbe-Disease from intervention effects
- Sharper review detection: explicit phrases trigger T0/NONE
"""
import argparse, csv, json, os, sys, time
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

PREDICATES = ["contains", "produces", "increases_abundance_of", "decreases_abundance_of",
              "increased_in", "decreased_in", "increases_marker", "decreases_marker",
              "has_high_FODMAP_content_of"]
ENTITY_TYPES = ["Food", "Bioactive", "Microbe", "IBD_Outcome", "Pathway"]
EVIDENCE_TYPES = ["rct", "cohort", "case_control", "animal", "mechanistic",
                  "review", "meta_analysis"]
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

**Subject/object types MUST match the predicate's required combination.**

# OFF-SCOPE - ALWAYS return empty triples array:

- Antibiotics (vancomycin, mesalazine, sulfasalazine, neomycin, rifaximin)
- Drug pharmacokinetics, biologics, JAK inhibitors, anti-TNF
- Surgical/procedural (colonoscopy, surgery, moxibustion, acupuncture)
- Materials science / drug delivery (nanoparticles, hydrogels, barriers)
- Bioengineered diagnostics (calprotectin biosensors)
- Cancer surveillance (chromoendoscopy, dysplasia)
- Clinical surveys (prescription patterns, classification agreement)
- Phage therapy or microbiota transplant (FMT, WMT)
- Pure immunology focused on signaling (NF-kB, TLR4, MAPK, AKT, Th17/Treg) without food/microbe data
- Cytokine-only relationships (TNF, IL-6, IL-10 as subject/object)

# REVIEWS - ALWAYS return empty triples array:

If the abstract contains any of these phrases or patterns, it is a REVIEW:
- "this review", "we review", "we summarize", "we summarised"
- "narrative review", "systematic review", "in this paper, we discuss"
- "the current literature", "this article aims to discuss"
- Abstract describes the structure of the paper rather than findings (e.g. "Section 1 covers...")
- Abstract uses "we suggest", "we propose" without quantitative results

Reviews synthesize others' findings; they do NOT report novel diet/microbiome triples.

# CRITICAL: DIRECTIONALITY RULES

**Do NOT infer Microbe-Disease relationships from intervention effects.**

WRONG: Abstract says "Vancomycin reduced Clostridium perfringens in pouchitis patients" → DO NOT extract `Clostridium perfringens increased_in pouchitis`. This is inferring direction from the inverse of an intervention effect.

RIGHT: Only extract Microbe-Disease relationships when the abstract directly observes them: "Faecalibacterium was decreased in UC patients compared to controls" → extract `Faecalibacterium decreased_in UC`.

# CRITICAL: ANTI-LIST-SPLITTING

**If multiple taxa appear in a single list with the same effect description, extract ONLY the taxa that the abstract emphasizes individually.**

If abstract says: "abundance of Bacteroides, Alteromonas, Neisseria, Streptococcus, and Microbacterium increased" — this is a single observational pattern. Extract at most 1-2 of these (the most emphasized) unless the abstract provides individual statistics, mechanistic detail, or repeated mention for each taxon.

When in doubt, extract the strongest 1-2 taxa, not all of them.

# EXTRACTION RULES:

1. **evidence_span MUST be verbatim** - copy exact text. No paraphrasing.

2. **Use specific entity names** from the abstract. "F. prausnitzii" → "Faecalibacterium prausnitzii".

3. **Compounds-as-Food convention**: Bioactive compounds (resveratrol, curcumin, polysaccharide, peptide, oligosaccharide) administered as dietary intervention → `Food`.

4. **evidence_type**: rct, cohort, case_control, animal, mechanistic, review, meta_analysis

5. **confidence**: 0.85-0.90 (RCT/cohort with sample size), 0.75-0.80 (animal with mechanism), 0.70 (animal direct), 0.65 (hedged/indirect)

6. **When in doubt, SKIP.** False positives hurt precision more than false negatives hurt recall.

You MUST call the submit_triples tool to submit your extractions."""


def format_fewshot_example(annot_id, pmid, title, abstract, triples):
    parts = [f"<example>", f"<input>", f"PMID: {pmid}", f"Title: {title}",
             f"Abstract: {abstract[:1500]}", f"</input>", f"<output>"]
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
                "subject_name": t["subject_name"], "subject_type": t["subject_type"],
                "predicate": t["predicate"],
                "object_name": t["object_name"], "object_type": t["object_type"],
                "evidence_span": t["evidence_span"],
                "evidence_type": t["evidence_type"],
                "confidence": conf, "notes": t.get("notes", ""),
            })
        parts.append("submit_triples(")
        parts.append(json.dumps({"triples": json_triples}, indent=2))
        parts.append(')')
    parts.append('</output>'); parts.append('</example>')
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
        examples.append(format_fewshot_example(aid, src["pmid"], src["title"],
                                                src["abstract"], by_aid[aid]))
    return "\n\n".join(examples)


def load_split_abstracts(split_name, limit=None):
    split_path = PROCESSED / f"gold_split_{split_name}.tsv"
    with open(split_path, encoding="utf-8") as f:
        split_rows = list(csv.DictReader(f, delimiter="\t"))
    split_ids = sorted(set(r["annot_id"] for r in split_rows))
    with open(PROCESSED / "gold_standard_to_annotate.tsv", encoding="utf-8") as f:
        source = {r["annot_id"]: r for r in csv.DictReader(f, delimiter="\t")}
    abstracts = [{"annot_id": aid, "pmid": source[aid]["pmid"],
                  "title": source[aid]["title"], "abstract": source[aid]["abstract"]}
                 for aid in split_ids]
    if limit: abstracts = abstracts[:limit]
    return abstracts


def validate_triple(t):
    expected = PREDICATE_TYPES.get(t.get("predicate"))
    if not expected: return False
    return (t.get("subject_type"), t.get("object_type")) == expected


def extract_one(client, abs_data, fewshot_text):
    user_content = f"""Here are example abstracts and the correct extractions:

{fewshot_text}

---

Now extract from this abstract:

PMID: {abs_data["pmid"]}
Title: {abs_data["title"]}
Abstract: {abs_data["abstract"][:5000]}

Before calling submit_triples:
1. Check: is this a review or off-scope paper? If so, return empty array.
2. For each triple, verify (subject_type, predicate, object_type) matches the schema.
3. Check directionality: did you infer Microbe-Disease from intervention effect? Drop those.
4. Check list-splitting: did you split a single list of taxa? Keep only 1-2 most emphasized.

Call submit_triples now."""

    for attempt in range(MAX_RETRIES):
        try:
            response = client.messages.create(
                model=MODEL, max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT, tools=[EXTRACTION_TOOL],
                tool_choice={"type": "tool", "name": "submit_triples"},
                messages=[{"role": "user", "content": user_content}],
            )
            for block in response.content:
                if block.type == "tool_use" and block.name == "submit_triples":
                    triples = block.input.get("triples", [])
                    usage = {"input_tokens": response.usage.input_tokens,
                             "output_tokens": response.usage.output_tokens}
                    return triples, usage
            raise RuntimeError("No tool_use block")
        except Exception as e:
            print(f"      attempt {attempt+1}: {e}")
            time.sleep(2 ** attempt)
    return [], None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "test", "fewshot"], required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    fewshot_text = load_fewshot_examples()
    print(f"Few-shot: {len(fewshot_text):,} chars")

    abstracts = load_split_abstracts(args.split, args.limit)
    print(f"{len(abstracts)} abstracts to extract\n")

    output_path = EXTRACTIONS_DIR / f"extractions_{args.split}_{args.version}.tsv"
    total_in = total_out = total_triples = total_dropped = 0
    rows = []

    for i, abs_data in enumerate(abstracts, 1):
        print(f"  [{i:>3}/{len(abstracts)}] {abs_data['annot_id']}...", end=" ", flush=True)
        triples, usage = extract_one(client, abs_data, fewshot_text)
        if usage:
            total_in += usage["input_tokens"]; total_out += usage["output_tokens"]

        valid = [t for t in triples if validate_triple(t)]
        dropped = len(triples) - len(valid)
        total_triples += len(valid); total_dropped += dropped
        print(f"{len(valid)} kept" + (f" ({dropped} dropped)" if dropped else ""))

        for tid, t in enumerate(valid, 1):
            rows.append({"annot_id": abs_data["annot_id"], "pmid": abs_data["pmid"],
                         "triple_id": f"T{tid}", **t})
        if not valid:
            rows.append({"annot_id": abs_data["annot_id"], "pmid": abs_data["pmid"],
                         "triple_id": "T0", "subject_name": "-", "subject_type": "-",
                         "predicate": "NONE", "object_name": "-", "object_type": "-",
                         "evidence_span": "-", "evidence_type": "-",
                         "confidence": 0, "notes": "Empty extraction"})

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
    print(f"  Abstracts:    {len(abstracts)}")
    print(f"  Kept:         {total_triples}")
    print(f"  Dropped:      {total_dropped}")
    print(f"  Avg/abstract: {total_triples/len(abstracts):.2f}")
    print(f"  Cost:         ${cost:.4f}")


if __name__ == "__main__":
    main()
