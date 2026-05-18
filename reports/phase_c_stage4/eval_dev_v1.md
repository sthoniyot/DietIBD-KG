# Phase C Stage 4 Evaluation: v1 on dev split

## Overall Metrics

| Metric | Value |
|---|---|
| True Positives  | 33 |
| False Positives | 113 |
| False Negatives | 37 |
| **Precision**   | **0.226** |
| **Recall**      | **0.471** |
| **F1**          | **0.306** |

## T0/NONE Abstracts (LLM correctly refused to extract)

| Metric | Count |
|---|---|
| Gold abstracts marked T0/NONE        | 29 |
| LLM also refused to extract          | 16 |
| LLM hallucinated triples in NONE abs | 13 (53 bogus triples) |

## Type Violations (predicate-type schema mismatch)

LLM produced **5 triples** where predicate doesn't match subject/object types:
  - A002: `IBD_Outcome-[decreased_in]->Bioactive` (expects ('Microbe', 'IBD_Outcome'))
  - A002: `IBD_Outcome-[decreased_in]->Microbe` (expects ('Microbe', 'IBD_Outcome'))
  - A002: `IBD_Outcome-[decreased_in]->Bioactive` (expects ('Microbe', 'IBD_Outcome'))
  - A032: `Microbe-[decreased_in]->Microbe` (expects ('Microbe', 'IBD_Outcome'))
  - A032: `Microbe-[decreased_in]->Microbe` (expects ('Microbe', 'IBD_Outcome'))

## Per-Predicate Breakdown

| Predicate | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|
| contains | 0 | 0 | 1 | 0.00 | 0.00 | 0.00 |
| decreased_in | 7 | 12 | 4 | 0.37 | 0.64 | 0.47 |
| decreases_abundance_of | 2 | 21 | 5 | 0.09 | 0.29 | 0.13 |
| decreases_marker | 11 | 26 | 16 | 0.30 | 0.41 | 0.34 |
| increased_in | 6 | 17 | 1 | 0.26 | 0.86 | 0.40 |
| increases_abundance_of | 6 | 33 | 7 | 0.15 | 0.46 | 0.23 |
| increases_marker | 0 | 3 | 0 | 0.00 | 0.00 | 0.00 |
| produces | 1 | 1 | 3 | 0.50 | 0.25 | 0.33 |

## Per-Stratum Breakdown

| Stratum | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|
| bioactive_ibd | 8 | 32 | 4 | 0.20 | 0.67 | 0.31 |
| diet_microbiome_ibd | 4 | 35 | 21 | 0.10 | 0.16 | 0.12 |
| general | 1 | 0 | 2 | 1.00 | 0.33 | 0.50 |
| microbe_ibd | 20 | 45 | 10 | 0.31 | 0.67 | 0.42 |
| off_scope | 0 | 1 | 0 | 0.00 | 0.00 | 0.00 |

## Sample False Positives (LLM extracted, no gold match)

  - A002: `Crohn's disease` -[decreased_in]-> `butyrate-synthetic capacity`
     evidence: "Reduced butyrate-synthetic capacity was found in patients with active and inactive CD..."
  - A002: `Crohn's disease` -[decreased_in]-> `butyrogenic taxa`
     evidence: "In CD, low BCoAT gene content was associated with ileal location, stenotic behaviour, increased inflammation, lower micr..."
  - A002: `ulcerative colitis` -[decreased_in]-> `butyrate-synthetic capacity`
     evidence: "Reduced butyrate-synthetic capacity was found in patients with active and inactive CD [p < 0.001 and p < 0.01, respectiv..."
  - A005: `Clostridium perfringens` -[increased_in]-> `pouchitis`
     evidence: "Antibiotic treatment reduced disease-associated bacteria such as Clostridium perfringens, Ruminococcus gnavus, and Klebs..."
  - A005: `Ruminococcus gnavus` -[increased_in]-> `pouchitis`
     evidence: "Antibiotic treatment reduced disease-associated bacteria such as Clostridium perfringens, Ruminococcus gnavus, and Klebs..."
  - A005: `Klebsiella pneumoniae` -[increased_in]-> `pouchitis`
     evidence: "Antibiotic treatment reduced disease-associated bacteria such as Clostridium perfringens, Ruminococcus gnavus, and Klebs..."
  - A005: `Faecalibacterium prausnitzii` -[decreased_in]-> `pouchitis`
     evidence: "Antibiotic treatment reduced disease-associated bacteria such as Clostridium perfringens, Ruminococcus gnavus, and Klebs..."
  - A006: `riboflavin` -[decreases_marker]-> `Crohn's disease`
     evidence: "Riboflavin supplementation significantly decreased serum levels of inflammatory markers..."
  ...and 105 more

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
  ...and 29 more