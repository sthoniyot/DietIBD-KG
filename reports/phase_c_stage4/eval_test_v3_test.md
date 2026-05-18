# Phase C Stage 4 Evaluation: v3_test on test split

## Overall Metrics

| Metric | Value |
|---|---|
| True Positives  | 17 |
| False Positives | 16 |
| False Negatives | 10 |
| **Precision**   | **0.515** |
| **Recall**      | **0.630** |
| **F1**          | **0.567** |

## T0/NONE Abstracts (LLM correctly refused to extract)

| Metric | Count |
|---|---|
| Gold abstracts marked T0/NONE        | 7 |
| LLM also refused to extract          | 6 |
| LLM hallucinated triples in NONE abs | 1 (2 bogus triples) |

## Type Violations (predicate-type schema mismatch)

LLM produced **0 triples** where predicate doesn't match subject/object types:

## Per-Predicate Breakdown

| Predicate | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|
| contains | 0 | 2 | 0 | 0.00 | 0.00 | 0.00 |
| decreased_in | 0 | 1 | 0 | 0.00 | 0.00 | 0.00 |
| decreases_abundance_of | 2 | 2 | 2 | 0.50 | 0.50 | 0.50 |
| decreases_marker | 7 | 3 | 2 | 0.70 | 0.78 | 0.74 |
| increased_in | 2 | 3 | 2 | 0.40 | 0.50 | 0.44 |
| increases_abundance_of | 5 | 5 | 4 | 0.50 | 0.56 | 0.53 |
| produces | 1 | 0 | 0 | 1.00 | 1.00 | 1.00 |

## Per-Stratum Breakdown

| Stratum | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|
| bioactive_ibd | 1 | 2 | 1 | 0.33 | 0.50 | 0.40 |
| diet_microbiome_ibd | 7 | 4 | 0 | 0.64 | 1.00 | 0.78 |
| general | 0 | 4 | 6 | 0.00 | 0.00 | 0.00 |
| microbe_ibd | 9 | 6 | 3 | 0.60 | 0.75 | 0.67 |

## Sample False Positives (LLM extracted, no gold match)

  - A010: `oat β-glucan` -[increases_abundance_of]-> `short chain fatty acid-producing bacteria`
     evidence: "Analysis of gut microbiota community showed that β-glucan treatment modulated gut microbial composition and structure at..."
  - A010: `oat β-glucan` -[contains]-> `β-glucan`
     evidence: "oat β-glucan..."
  - A019: `α-lactalbumin hydrolysate` -[contains]-> `antioxidant`
     evidence: "α-LA hydrolysate, which boasts a high antioxidant capacity..."
  - A020: `fish collagen peptide` -[increases_abundance_of]-> `gut microbiota`
     evidence: "FCP modulated the dysbiosis of gut microbiota toward a balanced state..."
  - A033: `Bacteroides` -[increased_in]-> `ulcerative colitis`
     evidence: "there were dynamic changes of gut microbiome in DSS-induced UC model: the relative abundance of intestinal flora increas..."
  - A033: `Lactobacillus` -[decreased_in]-> `ulcerative colitis`
     evidence: "and decreased first and then increased in Lactobacillus, Muribaculum, norank_f_Muribaculaceae..."
  - A042: `Bacteroides` -[increased_in]-> `inflammatory bowel disease`
     evidence: "Colonizing GF Hsp60Δ/ΔIEC mice with the synthetic community OMM12 reveals expansion of metabolically flexible Bacteroide..."
  - A042: `Bacteroides caecimuris` -[increased_in]-> `inflammatory bowel disease`
     evidence: "B. caecimuris mono-colonization recapitulates the injury..."
  ...and 8 more

## Sample False Negatives (gold has, LLM missed)

  - A033: `Enterorhabdus` -[increased_in]-> `ulcerative colitis`
     evidence: "in addition, Bifidobacterium, Coriobacteriaceae_UCG-002 and Enterorhabdus did not change in the first 14 days but increa..."
  - A043: `Ophiopogonin D` -[decreases_abundance_of]-> `Enterobacter`
     evidence: "and a decrease in the abundance of genera such as Enterobacter...."
  - A044: `Akkermansia muciniphila` -[increased_in]-> `ulcerative colitis`
     evidence: "which was significantly upregulated in DSS mice in our experimental context...."
  - A065: `propionic acid` -[decreases_marker]-> `ulcerative colitis`
     evidence: "Propionate effectively alleviated UC symptoms... These results strongly support the potential use of propionate in the c..."
  - A087: `Lactobacillus combination` -[decreases_marker]-> `ulcerative colitis`
     evidence: "Combination treatment with two Lactobacillus strains strongly ameliorates colitis symptoms in the mouse model..."
  - A087: `Lactobacillus combination` -[increases_abundance_of]-> `Muribaculaceae`
     evidence: "alters intestinal microbial composition close to normal by increasing abundances of Muribaculaceae, Akkermansia, Clostri..."
  - A087: `Lactobacillus combination` -[increases_abundance_of]-> `Akkermansia`
     evidence: "alters intestinal microbial composition close to normal by increasing abundances of Muribaculaceae, Akkermansia, Clostri..."
  - A087: `Lactobacillus combination` -[increases_abundance_of]-> `Oscillospiraceae`
     evidence: "alters intestinal microbial composition close to normal by increasing abundances of Muribaculaceae, Akkermansia, Clostri..."
  ...and 2 more