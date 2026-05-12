# Phase C: LLM Extraction from Biomedical Literature - Design Document

**Purpose:** Expand DietIBD-KG beyond curated databases (Phase B: 20,254 triples)
by extracting structured triples from PubMed abstracts. Target: ~20,000-30,000
additional triples, bringing total KG to ~50,000.

**Status:** Design only. No implementation yet. Pending: gold-standard
annotation (Stage 3) before any production extraction.

---

## 1. Scope and Rationale

### 1.1 What Phase C Adds Beyond Phase B

Phase B curated five sources providing strong but incomplete coverage:
- Disbiome: microbe-disease, but only ~750 IBD-relevant triples
- FooDB: food-bioactive, but missing many compounds (e.g., DHA, butyric acid)
- Bolte 2021: peer-reviewed but single-study, 1,425 subjects
- FODMAP: food classifications, no mechanistic detail
- KEGG: pathway-level only, no human/cohort evidence

**Gaps that PubMed extraction fills:**
- Recent findings (2022-2026) not yet in curated databases
- Mechanistic claims linking dietary components to specific IBD pathways
- Cohort findings from individual studies not aggregated in Disbiome
- Negative/contradictory findings (important for honest KG)
- Cytokine and immune-mediator relationships (sparse in Phase B)

### 1.2 What Phase C Does NOT Do

Explicitly out of scope to keep extraction tractable:
- Full-text article extraction (abstracts only)
- Pre-clinical mechanistic studies in cell culture (animal models acceptable, in vitro deferred)
- Quantitative effect sizes (extraction captures direction, not magnitude)
- Methodological details (sample sizes captured, but not statistical tests)
- Therapy/drug relationships (focus stays on diet -> microbiome -> IBD)

---

## 2. Corpus Selection

### 2.1 PubMed Query Strategy

Three search streams, each producing a candidate abstract pool. Queries use
PubMed's standard syntax (MeSH terms, field tags like [Title/Abstract], date
range [PDAT]). Final queries refined during Stage 2 implementation.

**Stream 1: Diet-microbiome-IBD core**
Combines IBD MeSH terms with microbiome MeSH terms with diet/nutrition/food
terms, filtered to 2018-2026 publication date.
Estimated yield: 3,000-5,000 abstracts.

**Stream 2: Specific bioactive-IBD relationships**
Combines IBD terms with bioactive compound names: butyrate, SCFA, tryptophan,
bile acid, indole, polyphenol, omega-3, fiber. Date range 2015-2026.
Estimated yield: 5,000-8,000 abstracts.

**Stream 3: Microbe-IBD findings (recent)**
Combines IBD terms with specific microbe names: Faecalibacterium, Akkermansia,
Roseburia, Bacteroides, Lactobacillus, Bifidobacterium, plus metagenomics term.
Date range 2020-2026.
Estimated yield: 4,000-6,000 abstracts.

**Combined deduplicated pool:** ~12,000-18,000 unique abstracts.

### 2.2 Filtering Before LLM

To keep API costs and noise down, exclude before extraction:
- Reviews/meta-analyses with no novel findings (Publication Type = Review)
- Abstracts shorter than 100 words (likely non-research)
- Non-English (PubMed LA=eng filter)
- Editorial/letter publication types

After filtering, target corpus: ~8,000-12,000 abstracts.

### 2.3 Implementation

Use Biopython's Entrez interface with:
- Email registered to user account (required by NCBI policy)
- API key from NCBI for higher rate limits (3 req/sec without key, 10 req/sec with)
- Batch retrieval (200 PMIDs per esummary/efetch call)
- Cache abstracts locally in data/raw/pubmed/abstracts.jsonl

---

## 3. Extraction Schema

### 3.1 Triple Structure (matches Phase B schema)

Each extracted triple matches the existing Triple dataclass with these fields:
subject_id, subject_label, subject_type, predicate, object_id, object_label,
object_type, source="PubMed", source_id=PMID, publication_id=DOI,
evidence_type, confidence, sample_type, method, notes (with evidence span).

### 3.2 Allowed Entity Types

Identical to Phase B vocabulary. **The LLM does NOT invent new entity types.**

| Type | Resolution target |
|------|-------------------|
| Food | FoodOn (FOODON:NNNNNNNN) |
| Bioactive | ChEBI (CHEBI:NNNNN) |
| Metabolite | ChEBI (CHEBI:NNNNN) |
| Microbe | NCBI Taxonomy (NCBITaxon:NNNNN) |
| Cytokine | UniProt (UniProt:NNNNN) |
| IBD_Outcome | DOID or HPO |
| Pathway | KEGG (KEGG:mapNNNNN) |
| Disease | DOID |

The LLM emits entity names as natural language. A post-processing step
resolves names to ontology IDs using the existing cascaded matcher.
Unresolvable entities flag the triple for manual review.

### 3.3 Allowed Predicates

Restricted to existing vocabulary plus three additions for literature claims:

**Existing (carried from Phase B):**
- contains, produces (Food/Microbe -> Bioactive)
- increases_abundance_of, decreases_abundance_of (Food -> Microbe)
- increased_in, decreased_in (Microbe -> IBD_Outcome)
- increases_marker, decreases_marker (Food -> IBD_Outcome)
- involves (Pathway -> Bioactive)
- has_high_FODMAP_content_of, is_low_FODMAP_food (Food -> Bioactive)

**New for Phase C:**
- associates_with (general undirected; for hedged claims like "linked to")
- mechanistic_link (paper proposes a mechanism; weaker than direct evidence)
- contradicts (paper explicitly contradicts prior finding)

The LLM is given the full list with one-sentence definitions in the prompt.

### 3.4 Evidence Types

Mapped from abstract methodology:

| Evidence Type | When to assign | Confidence baseline |
|---------------|----------------|---------------------|
| rct | Randomized controlled trial, human | 0.85 |
| cohort | Observational human cohort with n>50 | 0.80 |
| case_control | Case-control study | 0.78 |
| animal | Mouse/rat in vivo | 0.70 |
| in_vitro | Cell culture | excluded |
| review | Narrative review, no original data | 0.65 |
| mechanistic | Proposed mechanism only | 0.65 |
| meta_analysis | Pooled cross-study | 0.88 |

### 3.5 Confidence Scoring

Phase C confidence is generally lower than Phase B because:
- Single-study findings (vs curated meta-analysis in Disbiome)
- Extraction noise (LLM may misinterpret hedged claims)
- No quantitative ranking by FDR

Phase C confidence range: 0.50-0.85.
- Reserved 0.85+ for meta-analysis with explicit numerical findings
- Default 0.70 for cohort/RCT findings
- 0.60 for hedged or mechanistic claims
- 0.50 floor for any extracted triple

The LLM emits its own confidence in [0, 1]. We map and bound to our scale:
final_confidence = max(0.5, min(0.85, llm_confidence * evidence_factor))

### 3.6 Evidence Span (Required Field)

Every extracted triple must include the exact sentence from the abstract that
supports it. Stored in the notes field. Triples without evidence spans are
dropped. The evidence span is what makes the KG auditable.

---

## 4. LLM Prompt Strategy

### 4.1 Model Choice

Primary: **GPT-4o-mini via Batch API**
- 0.075 USD / 0.30 USD per million tokens (batch rate)
- 128K context window (room for abstract + schema + few-shot examples)
- Strong biomedical comprehension at this price tier

Fallback for validation pass on low-confidence extractions:
- GPT-4o or Claude Sonnet 4.6 (~20-30x more expensive, ~10% of corpus)

### 4.2 Prompt Structure

System prompt (cached): task definition, entity types, predicate vocabulary,
output JSON schema, 5-7 few-shot examples covering simple food-bioactive,
microbe-disease with effect direction, hedged claim, explicit no-finding,
multi-triple from one sentence, off-scope abstract.

User prompt (per abstract): PMID, title, abstract text, instruction to emit
JSON list (empty list if no extractable triples).

The system prompt is cached (90 percent discount on cached input tokens)
since it is identical across all 12,000+ requests.

### 4.3 Output JSON Schema (strict)

Each extracted item has: subject_name, subject_type, predicate, object_name,
object_type, evidence_span (exact quote), evidence_type, sample_size (or null),
llm_confidence (0-1 float).

Enforced via OpenAI's response_format=json_object parameter.

### 4.4 Post-Extraction Pipeline

For each LLM-emitted triple:
1. Parse JSON; reject if malformed
2. Resolve subject_name -> ontology ID via cascaded matcher
3. Resolve object_name -> ontology ID via cascaded matcher
4. If either ID unresolved, flag for manual review (don't drop yet)
5. Check predicate against allowed vocabulary; reject if invalid
6. Check evidence_span is non-empty and >20 characters
7. Compute final confidence from llm_confidence x evidence_type factor
8. Emit Triple object matching Phase B schema

---

## 5. Gold-Standard Annotation Plan

### 5.1 Purpose

A held-out set of abstracts annotated by hand (by you, the PhD student)
serving as ground truth for prompt iteration and final precision/recall
reporting.

### 5.2 Size and Composition

Target: 100 abstracts, stratified across:
- 30 diet-microbiome (matched to Stream 1)
- 30 microbe-IBD (matched to Stream 3)
- 20 bioactive-IBD (matched to Stream 2)
- 10 review articles (should produce few/no extractions)
- 10 negative or contradictory findings (test for honesty)

### 5.3 Annotation Process

For each abstract:
1. Read abstract carefully
2. Identify every relation a perfect system should extract
3. For each, write subject + predicate + object + evidence span + your confidence
4. Mark ambiguous cases with notes

Time estimate: 5-8 minutes per abstract x 100 = 8-13 hours of focused work,
split across 2-4 sessions.

Output: data/processed/gold_standard_annotations.tsv (committed to git).

### 5.4 Metrics

Compute against the gold standard:
- Precision = (correct LLM extractions) / (all LLM extractions)
- Recall = (correct LLM extractions) / (all gold extractions)
- F1 = harmonic mean

Target: precision > 0.80, recall > 0.60 before running production extraction.
These are realistic targets for biomedical IE; perfection is impossible.

A "correct" extraction matches the gold on subject, predicate, object
(after ontology resolution; minor name variants accepted).

### 5.5 Inter-annotator Agreement (optional, defer)

If a collaborator can re-annotate 20 of the 100 abstracts, compute Cohen's
kappa for inter-annotator agreement. Useful for the paper but not blocking.

---

## 6. Honesty and Limitations

### 6.1 What Phase C Cannot Do

- Cannot extract from full-text articles. Only abstracts.
- Cannot resolve every entity name. Some microbe names, strain identifiers,
  and chemical class names will not match ontologies cleanly.
- Cannot fully separate human-derived from animal-derived findings.
- Cannot match expert-curated quality. Disbiome triples will always be
  higher quality than Phase C triples. Confidence tiers reflect this.

### 6.2 Failure Modes to Watch For

- Hallucinated entities: LLM emits "Bifidobacterium IBDX" which doesn't exist.
  Caught by ontology resolution (no match -> manual review).
- Direction errors: LLM swaps subject and object. Caught by few-shot examples
  and the gold standard.
- Hedge-as-fact: Paper says "may be associated with" and LLM extracts as
  definitive. Mitigated via associates_with predicate + confidence cap.
- Off-scope extraction: LLM extracts drug-disease triples that aren't
  diet-related. Mitigated by explicit scope in prompt.
- Duplicate extraction: Same triple extracted from multiple abstracts. This
  is good - provides multi-source evidence. Handled in KG assembly.

### 6.3 Validation Beyond Gold Standard

After production extraction:
- Spot-check 100 random extracted triples for evidence-span accuracy
- Compare extracted Disbiome-style triples (microbe-IBD) to actual Disbiome
  triples; mismatch rate gives an external sanity check
- Reviewer-facing: present per-predicate precision/recall in supplementary

---

## 7. Execution Plan and Time Budget

| Stage | Deliverable | Time | Status |
|-------|-------------|------|--------|
| 1. Schema design | This document | 1-2 hours | Done tonight |
| 2. Corpus selection | data/raw/pubmed/abstracts.jsonl | 2-3 hours | Pending |
| 3. Gold standard | data/processed/gold_standard_annotations.tsv | 8-13 hours | Pending |
| 4. Prompt engineering | src/extraction/prompt.py + iteration | 1-2 days | Pending |
| 5. Production extraction | data/processed/triples_pubmed.tsv | 1-2 days | Pending |
| 6. Validation report | docs/phase_c_validation.md | 4-6 hours | Pending |

Total Phase C time estimate: 2-3 weeks of part-time PhD work.
API cost estimate: 20-50 USD total.

---

## 8. Decision Log

Decisions made in this design that may be revisited:

1. Abstracts only, not full text. Rationale: tractable scope, sufficient for
   KG expansion. Full-text deferred to a potential follow-up paper.

2. GPT-4o-mini primary, not Claude Haiku. Rationale: 7x cheaper at comparable
   quality on biomedical text. May revisit after gold-standard evaluation if
   Haiku shows substantially better extraction.

3. In vitro studies excluded. Rationale: weakest evidence tier for human IBD
   claims. Mechanistic papers with in vivo validation acceptable.

4. Evidence span required. Rationale: makes every triple auditable to a
   specific abstract sentence. Non-negotiable for KG quality.

5. Three new predicates (associates_with, mechanistic_link, contradicts).
   Rationale: literature uses hedged language that doesn't fit Phase B's
   curated predicates. Need extraction-specific vocabulary.
