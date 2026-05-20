# DietIBD-KG — Objective 1 QA & Summary Statistics

Generated: 2026-05-20 14:57

## 1. Overview

- **Total nodes:** 4,610
- **Total edges:** 16,172
- **Unique (subject, predicate, object) triples:** 14,876
- **Total edges (with evidence multiplicity):** 16,172
- **Evidence multiplicity factor:** 1.09 (edges per unique triple — LLM triples reported by multiple papers)

## 2. Integrity Checks

| Check | Count | Status |
|---|---|---|
| Orphan nodes (degree 0) | 0 | PASS |
| Self-loop edges | 0 | PASS |
| Nodes missing id/label | 0 | PASS |
| Edges missing sources property | 0 | PASS |
| LLM edges missing evidence_pmid | 0 | PASS |
| Duplicate node IDs | 0 | PASS |

## 3. Schema Validation

Edge endpoint types vs expected schema (9 core predicates):

| Relationship | Expected | Observed (subject -> object) | Violations |
|---|---|---|---|
| CONTAINS | {Food} -> {Bioactive} | Food->Bioactive (7089) | 0 |
| PRODUCES | {Microbe} -> {Bioactive} | Microbe->Bioactive (638) | 0 |
| INCREASES_ABUNDANCE_OF | {Bioactive|Food|Microbe} -> {Microbe} | Food->Microbe (1925), Bioactive->Microbe (71), Microbe->Microbe (19) | 0 |
| DECREASES_ABUNDANCE_OF | {Bioactive|Food|Microbe} -> {Microbe} | Food->Microbe (947), Bioactive->Microbe (30), Microbe->Microbe (10) | 0 |
| INCREASED_IN | {Microbe} -> {IBD_Outcome} | Microbe->IBD_Outcome (1179) | 0 |
| DECREASED_IN | {Microbe} -> {IBD_Outcome} | Microbe->IBD_Outcome (1198) | 0 |
| INCREASES_MARKER | {Bioactive|Food|Microbe} -> {IBD_Outcome} | Food->IBD_Outcome (145), Bioactive->IBD_Outcome (2) | 0 |
| DECREASES_MARKER | {Bioactive|Food|Microbe} -> {IBD_Outcome} | Food->IBD_Outcome (2086), Bioactive->IBD_Outcome (183), Microbe->IBD_Outcome (42) | 0 |
| HAS_HIGH_FODMAP_CONTENT_OF | {Food} -> {Bioactive} | Food->Bioactive (49) | 0 |

**Total schema violations across core predicates: 0**

Curated-only relationship types (endpoint distribution, informational):

| Relationship | Endpoint types |
|---|---|
| INVOLVES | Pathway->Bioactive (510) |
| IS_LOW_FODMAP_FOOD | Food->Bioactive (38) |
| MODULATES_CLUSTER | Food->Microbe (11) |

## 4. Node Statistics

| Node type | Count | % of nodes |
|---|---|---|
| Food | 2,615 | 56.7% |
| Microbe | 959 | 20.8% |
| Bioactive | 760 | 16.5% |
| IBD_Outcome | 263 | 5.7% |
| Pathway | 13 | 0.3% |

- **Curated (pre-existing) nodes:** 1,476
- **LLM-introduced nodes:** 3,134

## 5. Edge Statistics by Relationship Type

| Relationship | Total | Curated | LLM |
|---|---|---|---|
| CONTAINS | 7,089 | 6,884 | 205 |
| DECREASES_MARKER | 2,311 | 4 | 2,307 |
| INCREASES_ABUNDANCE_OF | 2,015 | 58 | 1,957 |
| DECREASED_IN | 1,198 | 282 | 916 |
| INCREASED_IN | 1,179 | 216 | 963 |
| DECREASES_ABUNDANCE_OF | 987 | 56 | 931 |
| PRODUCES | 638 | 0 | 638 |
| INVOLVES | 510 | 510 | 0 |
| INCREASES_MARKER | 147 | 3 | 144 |
| HAS_HIGH_FODMAP_CONTENT_OF | 49 | 46 | 3 |
| IS_LOW_FODMAP_FOOD | 38 | 38 | 0 |
| MODULATES_CLUSTER | 11 | 11 | 0 |

## 6. Provenance & Evidence

| Source | Edges | % |
|---|---|---|
| LLM | 8,064 | 49.9% |
| curated | 8,108 | 50.1% |

Edges per source label (sources property unwound):

| Source label | Edges |
|---|---|
| LLM | 8,064 |
| FooDB | 6,884 |
| KEGG | 510 |
| Disbiome | 498 |
| Bolte2021 | 132 |
| FODMAP_consensus | 84 |

LLM edge confidence distribution:

- min=0.65, Q1=0.80, median=0.80, Q3=0.85, max=0.95, mean=0.804

LLM edge evidence types:

| Evidence type | Edges |
|---|---|
| animal | 5,304 |
| cohort | 1,634 |
| mechanistic | 730 |
| rct | 188 |
| case_control | 131 |
| meta_analysis | 42 |
| review | 35 |

- **Unique PubMed IDs cited across LLM edges:** 3,072

## 7. Graph Topology

Degree distribution (undirected, all node types):

- min=1, median=2, mean=7.0, p90=15, max=2278

Degree by node type:

| Node type | Nodes | Mean degree | Max degree |
|---|---|---|---|
| Pathway | 13 | 39.2 | 81 |
| IBD_Outcome | 263 | 18.4 | 2278 |
| Bioactive | 760 | 11.3 | 517 |
| Microbe | 959 | 6.4 | 335 |
| Food | 2,615 | 4.7 | 35 |

Top 15 hub entities (highest degree):

| Rank | Type | Entity | Degree |
|---|---|---|---|
| 1 | IBD_Outcome | ulcerative colitis | 2278 |
| 2 | IBD_Outcome | Crohn's disease | 786 |
| 3 | IBD_Outcome | inflammatory bowel disease | 646 |
| 4 | Bioactive | L-tryptophan | 517 |
| 5 | Bioactive | L-tyrosine | 507 |
| 6 | Bioactive | choline | 490 |
| 7 | IBD_Outcome | colitis | 421 |
| 8 | Bioactive | glycine betaine | 389 |
| 9 | Bioactive | genistein | 344 |
| 10 | Bioactive | acetate | 344 |
| 11 | Microbe | Lactobacillus | 335 |
| 12 | Bioactive | daidzein | 329 |
| 13 | Bioactive | D-mannitol | 326 |
| 14 | Bioactive | trans-resveratrol | 326 |
| 15 | Bioactive | raffinose | 322 |

Connected components (treating edges as undirected):

- **Number of components:** 53
- **Largest component:** 4,437 nodes (96.2% of graph)
- **Singleton components:** 0
- **Component size distribution (top 10):** [4437, 25, 18, 7, 5, 4, 4, 4, 4, 4]

## 8. Summary for Paper

Headline numbers for the manuscript Results section:

- DietIBD-KG comprises 4,610 nodes and 16,172 edges
- 14,876 unique diet-microbiome-IBD relationships
- Dual provenance: curated databases + LLM-extracted literature
- 3,072 PubMed articles cited as edge-level evidence
- Largest connected component covers 96.2% of all nodes
- 0 schema violations among core predicates