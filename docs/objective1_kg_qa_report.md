# DietIBD-KG — Objective 1 QA & Summary Statistics

Generated: 2026-05-21 15:21

## 1. Overview

- **Total nodes:** 4,603
- **Total edges:** 16,146
- **Unique (subject, predicate, object) triples:** 14,850
- **Total edges (with evidence multiplicity):** 16,146
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
| CONTAINS | {Food} -> {Bioactive} | Food->Bioactive (7055) | 0 |
| PRODUCES | {Microbe} -> {Bioactive} | Microbe->Bioactive (647) | 0 |
| INCREASES_ABUNDANCE_OF | {Bioactive|Food|Microbe} -> {Microbe} | Food->Microbe (1194), Bioactive->Microbe (643), Microbe->Microbe (178) | 0 |
| DECREASES_ABUNDANCE_OF | {Bioactive|Food|Microbe} -> {Microbe} | Food->Microbe (642), Bioactive->Microbe (280), Microbe->Microbe (65) | 0 |
| INCREASED_IN | {Microbe} -> {IBD_Outcome} | Microbe->IBD_Outcome (1179) | 0 |
| DECREASED_IN | {Microbe} -> {IBD_Outcome} | Microbe->IBD_Outcome (1198) | 0 |
| INCREASES_MARKER | {Bioactive|Food|Microbe} -> {IBD_Outcome} | Food->IBD_Outcome (112), Bioactive->IBD_Outcome (28), Microbe->IBD_Outcome (7) | 0 |
| DECREASES_MARKER | {Bioactive|Food|Microbe} -> {IBD_Outcome} | Food->IBD_Outcome (1265), Bioactive->IBD_Outcome (798), Microbe->IBD_Outcome (248) | 0 |
| HAS_HIGH_FODMAP_CONTENT_OF | {Food} -> {Bioactive} | Food->Bioactive (48) | 0 |

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
| Food | 1,870 | 40.6% |
| Bioactive | 1,303 | 28.3% |
| Microbe | 1,154 | 25.1% |
| IBD_Outcome | 263 | 5.7% |
| Pathway | 13 | 0.3% |

- **Curated (pre-existing) nodes:** 1,476
- **LLM-introduced nodes:** 3,127

## 5. Edge Statistics by Relationship Type

| Relationship | Total | Curated | LLM |
|---|---|---|---|
| CONTAINS | 7,055 | 6,884 | 171 |
| DECREASES_MARKER | 2,311 | 4 | 2,307 |
| INCREASES_ABUNDANCE_OF | 2,015 | 58 | 1,957 |
| DECREASED_IN | 1,198 | 282 | 916 |
| INCREASED_IN | 1,179 | 216 | 963 |
| DECREASES_ABUNDANCE_OF | 987 | 56 | 931 |
| PRODUCES | 647 | 0 | 647 |
| INVOLVES | 510 | 510 | 0 |
| INCREASES_MARKER | 147 | 3 | 144 |
| HAS_HIGH_FODMAP_CONTENT_OF | 48 | 46 | 2 |
| IS_LOW_FODMAP_FOOD | 38 | 38 | 0 |
| MODULATES_CLUSTER | 11 | 11 | 0 |

## 6. Provenance & Evidence

| Source | Edges | % |
|---|---|---|
| curated | 8,108 | 50.2% |
| LLM | 8,038 | 49.8% |

Edges per source label (sources property unwound):

| Source label | Edges |
|---|---|
| LLM | 8,038 |
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
| animal | 5,293 |
| cohort | 1,633 |
| mechanistic | 716 |
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
| Bioactive | 1,303 | 7.7 | 517 |
| Microbe | 1,154 | 5.7 | 335 |
| Food | 1,870 | 5.5 | 35 |

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
| 9 | Bioactive | acetate | 344 |
| 10 | Bioactive | genistein | 344 |
| 11 | Microbe | Lactobacillus | 335 |
| 12 | Bioactive | daidzein | 329 |
| 13 | Bioactive | D-mannitol | 326 |
| 14 | Bioactive | trans-resveratrol | 326 |
| 15 | Bioactive | raffinose | 322 |

Connected components (treating edges as undirected):

- **Number of components:** 52
- **Largest component:** 4,432 nodes (96.3% of graph)
- **Singleton components:** 0
- **Component size distribution (top 10):** [4432, 25, 18, 7, 5, 4, 4, 4, 4, 4]

## 8. Summary for Paper

Headline numbers for the manuscript Results section:

- DietIBD-KG comprises 4,603 nodes and 16,146 edges
- 14,850 unique diet-microbiome-IBD relationships
- Dual provenance: curated databases + LLM-extracted literature
- 3,072 PubMed articles cited as edge-level evidence
- Largest connected component covers 96.3% of all nodes
- 0 schema violations among core predicates