# Phase C Stage 4 Evaluation: v2_aligned on dev split

## Overall Metrics

| Metric | Value |
|---|---|
| True Positives  | 44 |
| False Positives | 75 |
| False Negatives | 17 |
| **Precision**   | **0.370** |
| **Recall**      | **0.721** |
| **F1**          | **0.489** |

## T0/NONE Abstracts (LLM correctly refused to extract)

| Metric | Count |
|---|---|
| Gold abstracts marked T0/NONE        | 34 |
| LLM also refused to extract          | 23 |
| LLM hallucinated triples in NONE abs | 11 (35 bogus triples) |

## Type Violations (predicate-type schema mismatch)

LLM produced **0 triples** where predicate doesn't match subject/object types:

## Per-Predicate Breakdown

| Predicate | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|
| contains | 0 | 1 | 0 | 0.00 | 0.00 | 0.00 |
| decreased_in | 7 | 8 | 2 | 0.47 | 0.78 | 0.58 |
| decreases_abundance_of | 3 | 14 | 5 | 0.18 | 0.38 | 0.24 |
| decreases_marker | 17 | 15 | 6 | 0.53 | 0.74 | 0.62 |
| increased_in | 4 | 16 | 3 | 0.20 | 0.57 | 0.30 |
| increases_abundance_of | 10 | 18 | 0 | 0.36 | 1.00 | 0.53 |
| increases_marker | 0 | 3 | 0 | 0.00 | 0.00 | 0.00 |
| produces | 3 | 0 | 1 | 1.00 | 0.75 | 0.86 |

## Per-Stratum Breakdown

| Stratum | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|
| bioactive_ibd | 9 | 23 | 3 | 0.28 | 0.75 | 0.41 |
| diet_microbiome_ibd | 16 | 24 | 0 | 0.40 | 1.00 | 0.57 |
| general | 1 | 1 | 2 | 0.50 | 0.33 | 0.40 |
| microbe_ibd | 18 | 23 | 12 | 0.44 | 0.60 | 0.51 |
| off_scope | 0 | 1 | 0 | 0.00 | 0.00 | 0.00 |
| reviews | 0 | 3 | 0 | 0.00 | 0.00 | 0.00 |

## Sample False Positives (LLM extracted, no gold match)

  - A002: `butyrate-synthetic microbiota` -[decreased_in]-> `Crohn's disease`
     evidence: "Reduced butyrate-synthetic capacity was found in patients with active and inactive CD [p < 0.001 and p < 0.01, respectiv..."
  - A002: `butyrate-synthetic microbiota` -[decreased_in]-> `ulcerative colitis`
     evidence: "Reduced butyrate-synthetic capacity was found... only in active UC [p < 0.05]..."
  - A002: `dietary fiber` -[increases_abundance_of]-> `butyrate-synthetic microbiota`
     evidence: "Reduced BCoAT gene content in patients with CD was linked with a different regimen characterised by lower dietary fibre..."
  - A005: `Clostridium perfringens` -[increased_in]-> `pouchitis`
     evidence: "Antibiotic treatment reduced disease-associated bacteria such as Clostridium perfringens, Ruminococcus gnavus, and Klebs..."
  - A005: `Ruminococcus gnavus` -[increased_in]-> `pouchitis`
     evidence: "Antibiotic treatment reduced disease-associated bacteria such as Clostridium perfringens, Ruminococcus gnavus, and Klebs..."
  - A005: `Klebsiella pneumoniae` -[increased_in]-> `pouchitis`
     evidence: "Antibiotic treatment reduced disease-associated bacteria such as Clostridium perfringens, Ruminococcus gnavus, and Klebs..."
  - A005: `Faecalibacterium prausnitzii` -[decreased_in]-> `pouchitis`
     evidence: "Antibiotic treatment reduced disease-associated bacteria such as Clostridium perfringens, Ruminococcus gnavus, and Klebs..."
  - A008: `Bacteroides` -[increased_in]-> `irritable bowel syndrome`
     evidence: "the colonic mucosal enrichment of Bacteroides, Alteromonas, Neisseria, Streptococcus, and Microbacterium, may serve as a..."
  ...and 67 more

## Sample False Negatives (gold has, LLM missed)

  - A027: `tilapia head glycolipids` -[decreases_marker]-> `inflammatory bowel disease`
     evidence: "The results indicate that TH-GLs alleviate DSS-induced IBD in mice by decreasing the abundance of harmful gut microbiota..."
  - A027: `tilapia head glycolipids` -[decreases_abundance_of]-> `Escherichia`
     evidence: "Both sulfasalazine and TH-GLs decreased the DSS-induced enrichment of Gammaproteobacteria and Enterobacteriaceae...."
  - A032: `Escherichia` -[increased_in]-> `Crohn's disease`
     evidence: "AIEC was significantly more prevalent in ileal tissues of patients with CD than controls (30% vs 7.1%)...."
  - A040: `lactoferricin B` -[decreases_marker]-> `ulcerative colitis`
     evidence: "In conclusion, oral administration of LfcinB significantly alleviated DSS-induced UC...."
  - A040: `lactoferricin B` -[decreases_abundance_of]-> `Bacteroides`
     evidence: "It also significantly suppressed the relative abundance of potentially pathogenic bacteria (Bacteroides, Barnesiella and..."
  - A040: `lactoferricin B` -[decreases_abundance_of]-> `Barnesiella`
     evidence: "It also significantly suppressed the relative abundance of potentially pathogenic bacteria (Bacteroides, Barnesiella and..."
  - A040: `lactoferricin B` -[decreases_abundance_of]-> `Escherichia`
     evidence: "It also significantly suppressed the relative abundance of potentially pathogenic bacteria (Bacteroides, Barnesiella and..."
  - A047: `Lactobacillus` -[decreased_in]-> `ulcerative colitis`
     evidence: "At the genus level, the relevant abundance of Lactobacillus decreased..."
  ...and 9 more