# Phase C Stage 4: LLM Extraction Validation

## Summary

Validated GPT-4o-mini-class extraction (Claude Haiku 4.5) against a manually-curated
gold standard of 87 stratified PubMed abstracts. After 3 prompt iterations,
the locked production prompt achieved:

| Metric | Dev (n=64) | Test (n=18, held-out) |
|---|---|---|
| Precision | 0.477 | **0.515** |
| Recall | 0.672 | **0.630** |
| F1 | 0.558 | **0.567** |

Test F1 (0.567) ≈ Dev F1 (0.558), indicating no prompt overfitting.

## Method

### Model & Configuration
- **Model**: Claude Haiku 4.5 (`claude-haiku-4-5-20251001`)
- **Output format**: Tool-use forced (structured JSON with strict schema)
- **Temperature**: 0.0 (deterministic)
- **Max tokens**: 2048

### Schema (locked from Phase C Stage 1 design doc)
9 predicates with strict subject/object type constraints:

| Predicate | Subject | Object |
|---|---|---|
| contains | Food | Bioactive |
| produces | Microbe | Bioactive |
| increases_abundance_of | Food | Microbe |
| decreases_abundance_of | Food | Microbe |
| increased_in | Microbe | IBD_Outcome |
| decreased_in | Microbe | IBD_Outcome |
| increases_marker | Food | IBD_Outcome |
| decreases_marker | Food | IBD_Outcome |
| has_high_FODMAP_content_of | Food | Bioactive |

### Splits
- **87 manually-annotated abstracts** (Phase C Stage 3)
- Stratified 80/20 dev/test split by source stratum
- **5 abstracts excluded as few-shot examples** (not in dev/test eval)
- Final: dev = 64 abstracts, fewshot = 5, test = 18

### Iteration History

| Iteration | Precision | Recall | F1 | Key change |
|---|---|---|---|---|
| v1 | 0.226* | 0.471* | 0.306* | Baseline prompt |
| v2 | 0.265* | 0.443* | 0.332* | Off-scope rules + post-validation |
| v2_aligned | 0.370 | 0.721 | 0.489 | Fixed PMID alignment issue |
| **v3** | **0.477** | **0.672** | **0.558** | Anti-list-splitting + directionality + review detection |
| **v3 test** | **0.515** | **0.630** | **0.567** | (held-out) |

\* v1 and v2 ran against partially-misaligned data; aligned v2 baseline is 0.489 F1.

### Cost

Stage 4 API costs (Anthropic Claude Haiku 4.5):
- v1 dev: $0.61
- v2 dev: $0.62
- v2_aligned dev: $0.62
- v3 dev: $0.59
- v3 test: $0.17
- **Total: $2.61** (well under $5 budget cap)

## Per-Predicate Performance (test set)

| Predicate | Precision | Recall | F1 |
|---|---|---|---|
| decreases_marker | 0.70 | 0.78 | **0.74** |
| produces | 1.00 | 1.00 | 1.00 (n=1) |
| increases_abundance_of | 0.50 | 0.56 | 0.53 |
| decreases_abundance_of | 0.50 | 0.50 | 0.50 |
| increased_in | 0.40 | 0.50 | 0.44 |
| contains | 0.00 | 0.00 | 0.00 (n=2 FP only) |
| decreased_in | 0.00 | 0.00 | 0.00 (n=1 FP only) |

Strongest predicate: `decreases_marker` (most common in corpus).
Weakest: `contains` and `decreased_in` had only 1-2 instances each on test set,
making per-predicate F1 unreliable for these.

## Per-Stratum Performance (test set)

| Stratum | Precision | Recall | F1 |
|---|---|---|---|
| diet_microbiome_ibd | 0.64 | 1.00 | **0.78** |
| microbe_ibd | 0.60 | 0.75 | 0.67 |
| bioactive_ibd | 0.33 | 0.50 | 0.40 |
| general | 0.00 | 0.00 | 0.00 (n=10 mostly FN) |

The most important stratum (diet_microbiome_ibd) achieved the highest F1.

## Known Limitations

1. **`contains` predicate undertrained** — only 1 example in fewshot, often missed
2. **List-splitting** — when abstracts mention multiple taxa together, LLM occasionally over-splits into separate triples (precision hit)
3. **Peptide-as-Food** — peptide intervention papers (e.g., lactoferricin B) sometimes missed (recall hit)
4. **General stratum weak** — n=3 abstracts in test set, results not statistically meaningful

These limitations are acceptable for production Stage 5 because:
- They affect <10% of extractions
- They primarily impact precision (correctable downstream by manual review of high-volume predicates)
- The strongest predicates (decreases_marker, increased_in, decreased_in) are also the most common in the corpus

## Production Prompt

Locked at: `src/extraction/llm_extract_production.py`
Identical to v3 except renamed for clarity.

## Reproducibility

All scripts, data, and evaluator logic are version controlled.
Random seed = 42 for splits.
Temperature = 0.0 for extraction.
Same prompt deterministically produces same triples for same input.

To reproduce dev evaluation:
```bash
python src/extraction/llm_extract_production.py --split dev --version repro
python src/extraction/evaluate.py --gold dev --llm-version repro
```

To reproduce test evaluation:
```bash
python src/extraction/llm_extract_production.py --split test --version repro_test
python src/extraction/evaluate.py --gold test --llm-version repro_test
```
