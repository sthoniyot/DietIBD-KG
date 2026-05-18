# Phase C Stage 4 Evaluation: v2 on dev split

## Overall Metrics

| Metric | Value |
|---|---|
| True Positives  | 31 |
| False Positives | 86 |
| False Negatives | 39 |
| **Precision**   | **0.265** |
| **Recall**      | **0.443** |
| **F1**          | **0.332** |

## T0/NONE Abstracts (LLM correctly refused to extract)

| Metric | Count |
|---|---|
| Gold abstracts marked T0/NONE        | 29 |
| LLM also refused to extract          | 19 |
| LLM hallucinated triples in NONE abs | 10 (31 bogus triples) |

## Type Violations (predicate-type schema mismatch)

LLM produced **0 triples** where predicate doesn't match subject/object types:

## Per-Predicate Breakdown

| Predicate | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|
| contains | 0 | 2 | 1 | 0.00 | 0.00 | 0.00 |
| decreased_in | 6 | 4 | 5 | 0.60 | 0.55 | 0.57 |
| decreases_abundance_of | 2 | 14 | 5 | 0.12 | 0.29 | 0.17 |
| decreases_marker | 10 | 24 | 17 | 0.29 | 0.37 | 0.33 |
| increased_in | 4 | 15 | 3 | 0.21 | 0.57 | 0.31 |
| increases_abundance_of | 6 | 22 | 7 | 0.21 | 0.46 | 0.29 |
| increases_marker | 0 | 2 | 0 | 0.00 | 0.00 | 0.00 |
| produces | 3 | 3 | 1 | 0.50 | 0.75 | 0.60 |

## Per-Stratum Breakdown

| Stratum | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|
| bioactive_ibd | 9 | 27 | 3 | 0.25 | 0.75 | 0.38 |
| diet_microbiome_ibd | 4 | 29 | 21 | 0.12 | 0.16 | 0.14 |
| general | 1 | 1 | 2 | 0.50 | 0.33 | 0.40 |
| microbe_ibd | 17 | 26 | 13 | 0.40 | 0.57 | 0.47 |
| off_scope | 0 | 1 | 0 | 0.00 | 0.00 | 0.00 |
| reviews | 0 | 2 | 0 | 0.00 | 0.00 | 0.00 |

## Sample False Positives (LLM extracted, no gold match)

  - A006: `riboflavin` -[decreases_marker]-> `Crohn's disease`
     evidence: "Riboflavin supplementation significantly decreased serum levels of inflammatory markers..."
  - A006: `riboflavin` -[decreases_marker]-> `Crohn's disease`
     evidence: "Moreover, HBI was significantly decreased by riboflavin supplementation..."
  - A006: `riboflavin` -[decreases_abundance_of]-> `Enterobacteriaceae`
     evidence: "Riboflavin supplementation led to decreased Enterobacteriaceae in patients with low FC levels as determined by FISH..."
  - A008: `Bacteroides` -[increased_in]-> `irritable bowel syndrome`
     evidence: "the colonic mucosal enrichment of Bacteroides, Alteromonas, Neisseria, Streptococcus, and Microbacterium, may serve as a..."
  - A008: `Alteromonas` -[increased_in]-> `irritable bowel syndrome`
     evidence: "the colonic mucosal enrichment of Bacteroides, Alteromonas, Neisseria, Streptococcus, and Microbacterium, may serve as a..."
  - A008: `Neisseria` -[increased_in]-> `irritable bowel syndrome`
     evidence: "the colonic mucosal enrichment of Bacteroides, Alteromonas, Neisseria, Streptococcus, and Microbacterium, may serve as a..."
  - A008: `Streptococcus` -[increased_in]-> `irritable bowel syndrome`
     evidence: "the colonic mucosal enrichment of Bacteroides, Alteromonas, Neisseria, Streptococcus, and Microbacterium, may serve as a..."
  - A008: `Microbacterium` -[increased_in]-> `irritable bowel syndrome`
     evidence: "the colonic mucosal enrichment of Bacteroides, Alteromonas, Neisseria, Streptococcus, and Microbacterium, may serve as a..."
  ...and 78 more

## Sample False Negatives (gold has, LLM missed)

  - A002: `tea` -[contains]-> `theabrownin`
     evidence: "Theabrownin (TB), a core functional component of brick tea, has been reported to possess anti-obesity and lipid-lowering..."
  - A002: `tea` -[decreases_marker]-> `ulcerative colitis`
     evidence: "In the present study, we found that TB treatment significantly alleviated the clinical symptoms and colonic pathological..."
  - A002: `tea` -[increases_abundance_of]-> `Akkermansia`
     evidence: "TB treatment also modulated the gut microbiota composition, especially by increasing the abundance of Akkermansia...."
  - A003: `Allium tenuissimum flower polysaccharide` -[decreases_marker]-> `ulcerative colitis`
     evidence: "Overall, ATFP showed a significant mitigating effect against ulcerative colitis in mice, and it is expected to prove its..."
  - A004: `rice protein` -[decreases_marker]-> `ulcerative colitis`
     evidence: "Thus, RP may be an effective therapeutic dietary resource for ulcerative colitis...."
  - A004: `rice protein` -[increases_abundance_of]-> `Akkermansia`
     evidence: "Also, RP treatment could... regulate gut microbiota by enhancing the relative abundance of Akkermansia..."
  - A006: `jellyfish skin polysaccharide` -[decreases_marker]-> `ulcerative colitis`
     evidence: "JSP supplementation reduced the symptoms of colitis in mice, increased colon length, protected goblet cells, and improve..."
  - A011: `Faecalibacterium` -[decreased_in]-> `Crohn's disease`
     evidence: "In CD, low BCoAT gene content was associated with... decreased butyrogenic taxa...."
  ...and 31 more