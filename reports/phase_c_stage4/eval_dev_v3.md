# Phase C Stage 4 Evaluation: v3 on dev split

## Overall Metrics

| Metric | Value |
|---|---|
| True Positives  | 43 |
| False Positives | 43 |
| False Negatives | 18 |
| **Precision**   | **0.500** |
| **Recall**      | **0.705** |
| **F1**          | **0.585** |

## T0/NONE Abstracts (LLM correctly refused to extract)

| Metric | Count |
|---|---|
| Gold abstracts marked T0/NONE        | 34 |
| LLM also refused to extract          | 24 |
| LLM hallucinated triples in NONE abs | 10 (20 bogus triples) |

## Type Violations (predicate-type schema mismatch)

LLM produced **0 triples** where predicate doesn't match subject/object types:

## Per-Predicate Breakdown

| Predicate | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|
| decreased_in | 7 | 2 | 2 | 0.78 | 0.78 | 0.78 |
| decreases_abundance_of | 3 | 9 | 5 | 0.25 | 0.38 | 0.30 |
| decreases_marker | 19 | 10 | 4 | 0.66 | 0.83 | 0.73 |
| increased_in | 5 | 7 | 2 | 0.42 | 0.71 | 0.53 |
| increases_abundance_of | 8 | 12 | 2 | 0.40 | 0.80 | 0.53 |
| increases_marker | 0 | 2 | 0 | 0.00 | 0.00 | 0.00 |
| produces | 1 | 1 | 3 | 0.50 | 0.25 | 0.33 |

## Per-Stratum Breakdown

| Stratum | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|
| bioactive_ibd | 9 | 17 | 3 | 0.35 | 0.75 | 0.47 |
| diet_microbiome_ibd | 15 | 10 | 1 | 0.60 | 0.94 | 0.73 |
| general | 1 | 1 | 2 | 0.50 | 0.33 | 0.40 |
| microbe_ibd | 18 | 15 | 12 | 0.55 | 0.60 | 0.57 |

## Sample False Positives (LLM extracted, no gold match)

  - A002: `dietary fibre` -[increases_abundance_of]-> `butyrogenic taxa`
     evidence: "Reduced BCoAT gene content in patients with CD was linked with a different regimen characterised by lower dietary fibre...."
  - A008: `Bacteroides` -[increased_in]-> `irritable bowel syndrome`
     evidence: "the colonic mucosal enrichment of Bacteroides, Alteromonas, Neisseria, Streptococcus, and Microbacterium, may serve as a..."
  - A008: `Alteromonas` -[increased_in]-> `irritable bowel syndrome`
     evidence: "the colonic mucosal enrichment of Bacteroides, Alteromonas, Neisseria, Streptococcus, and Microbacterium, may serve as a..."
  - A011: `Jellyfish skin polysaccharide` -[decreases_marker]-> `colitis inflammation`
     evidence: "JSP modulated oxidative stress and inflammatory responses, which was demonstrated by reduced MPO activity, NO level, and..."
  - A015: `Allium tenuissimum polysaccharide` -[increases_abundance_of]-> `short-chain fatty acid producing bacteria`
     evidence: "ATFP also played an important role in regulating the structure of gut microbiota, which was specifically reflected in pr..."
  - A016: `heat-killed Saccharomyces boulardii` -[decreases_marker]-> `ulcerative colitis`
     evidence: "heat-killed S. boulardii maximally restored the composition, structure, and functionality of the intestinal microbiota t..."
  - A022: `Mediterranean diet pattern` -[increases_abundance_of]-> `Bacteroides vulgatus`
     evidence: "individuals with increased levels of the class Bacteroidia (Bacteroides vulgatus [B. vulgatus], B. uniformis, and B. aci..."
  - A023: `Sunset yellow` -[decreases_abundance_of]-> `Akkermansia muciniphila`
     evidence: "SY exposure both in vivo and in vitro inhibited the growth of Akkermansia muciniphila (AKK)..."
  ...and 35 more

## Sample False Negatives (gold has, LLM missed)

  - A018: `theabrownin` -[increases_abundance_of]-> `Eubacterium`
     evidence: "TB increased... the abundance of Akkermansia, Muribaculaceae, and Eubacterium_coprostanoligenes_group at the genus level..."
  - A027: `tilapia head glycolipids` -[decreases_abundance_of]-> `Escherichia`
     evidence: "Both sulfasalazine and TH-GLs decreased the DSS-induced enrichment of Gammaproteobacteria and Enterobacteriaceae...."
  - A027: `tilapia head glycolipids` -[increases_abundance_of]-> `Coprococcus`
     evidence: "However, TH-GLs had a selective increase in the enrichment of Akkermansia, Prevotellaceae, Oscillospira, Allobaculum, Bi..."
  - A032: `Roseburia` -[produces]-> `butyrate`
     evidence: "Presence of AIEC in ileal tissues was associated with more severe mucosa microbiota dysbiosis in CD with decreased diver..."
  - A040: `lactoferricin B` -[decreases_marker]-> `ulcerative colitis`
     evidence: "In conclusion, oral administration of LfcinB significantly alleviated DSS-induced UC...."
  - A040: `lactoferricin B` -[decreases_abundance_of]-> `Bacteroides`
     evidence: "It also significantly suppressed the relative abundance of potentially pathogenic bacteria (Bacteroides, Barnesiella and..."
  - A040: `lactoferricin B` -[decreases_abundance_of]-> `Barnesiella`
     evidence: "It also significantly suppressed the relative abundance of potentially pathogenic bacteria (Bacteroides, Barnesiella and..."
  - A040: `lactoferricin B` -[decreases_abundance_of]-> `Escherichia`
     evidence: "It also significantly suppressed the relative abundance of potentially pathogenic bacteria (Bacteroides, Barnesiella and..."
  ...and 10 more