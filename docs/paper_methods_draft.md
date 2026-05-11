# DietIBD-KG: Methods Draft

Draft of the Methods section for the DietIBD-KG resource paper. Updated as
ingestion phases are completed. Final version will be polished and revised
for submission.

**Current state:** Phase B (curated database ingestion) - 4 of 5 sources complete.
**Total triples ingested:** 19,744 from 4 sources.

---

## 1. Knowledge Graph Schema

DietIBD-KG models the diet-microbiome-IBD axis using a typed entity-relation
schema with eight entity types and 14 predicate types.

### 1.1 Entity Types

| Entity Type | Ontology | Example ID | Example Label |
|---|---|---|---|
| Food | FoodOn | FOODON:00002473 | apple |
| Bioactive | ChEBI | CHEBI:16243 | quercetin |
| Metabolite | ChEBI | CHEBI:28364 | EPA |
| Microbe | NCBI Taxonomy | NCBITaxon:853 | Faecalibacterium prausnitzii |
| Cytokine | UniProt (deferred) | UniProt:P01375 | TNF-alpha |
| IBD_Outcome | Disease Ontology + HPO | DOID:8778 / HP:0040156 | Crohn's disease / elevated fecal calprotectin |
| Pathway | KEGG (deferred) | KEGG:map00072 | Synthesis and degradation of ketone bodies |
| Disease | Disease Ontology | DOID:0050589 | inflammatory bowel disease |

### 1.2 Predicate Types

| Predicate | Subject Type | Object Type | Source Tables |
|---|---|---|---|
| contains | Food | Bioactive | FooDB |
| has_high_FODMAP_content_of | Food | Bioactive | FODMAP consensus |
| is_low_FODMAP_food | Food | Bioactive | FODMAP consensus |
| increases_abundance_of | Food | Microbe | Bolte 2021 (S7) |
| decreases_abundance_of | Food | Microbe | Bolte 2021 (S7) |
| modulates_cluster | Food | Microbe | Bolte 2021 (S4) |
| increases_marker | Food | IBD_Outcome | Bolte 2021 (S5) |
| decreases_marker | Food | IBD_Outcome | Bolte 2021 (S5) |
| increased_in | Microbe | IBD_Outcome | Disbiome |
| decreased_in | Microbe | IBD_Outcome | Disbiome |

### 1.3 Confidence Tiers

Every triple carries a confidence score in [0.5, 0.95]:

| Tier | Range | Evidence Source |
|---|---|---|
| Tier 4 (highest) | 0.90-0.95 | Peer-reviewed meta-analysis (Bolte 2021 with FDR<1e-3) |
| Tier 3 | 0.85-0.89 | Curated database with quantitative concentration (FooDB measured, FDR-significant) |
| Tier 2 | 0.80-0.84 | Curated database with qualitative evidence (Disbiome with weaker methods) |
| Tier 1 | 0.70-0.79 | Presence-only annotations (FooDB without measured concentration) |
| Tier 0 | 0.50-0.69 | Unverified or weak evidence (reserved for Phase C LLM extraction) |

---

## 2. Normalization Layer

Before ingestion, we built a unified normalization layer that resolves entity
names from heterogeneous source vocabularies to canonical ontology IDs.

### 2.1 Cascaded Matcher

For each lookup, the matcher tries match types in priority order:
1. **exact_label** — query equals the canonical label (case-insensitive)
2. **exact_synonym** — query equals a published synonym (case-insensitive)
3. **manual_mapping** — query is in a curated TSV (used for abbreviations like TMAO, EGCG, LPS)
4. **tokenized_label** — query word matches significant tokens (with stop-word filtering)
5. **substring_label** — query is a substring of the label
6. **substring_synonym** — query is a substring of a synonym
7. **no_match** — entity is dropped or flagged for review

The cascade is implemented in `src/normalization/ontology_loader.py` and is
shared across all ingestion scripts.

### 2.2 Ontologies Loaded

| Ontology | Format | Terms | Loader |
|---|---|---|---|
| FoodOn | OWL | 39,682 | owlready2 |
| ChEBI | OBO | 205,593 | pronto |
| Disease Ontology (DOID) | OBO | 14,638 | pronto |
| NCIT | OWL | 211,072 | owlready2 |
| Human Phenotype Ontology (HPO) | OBO | 19,944 | pronto |
| NCBI Taxonomy | DMP | 2,827,563 | custom parser |

All ontologies cached as pickled Python objects for sub-second reload.

### 2.3 Manual Mapping Tables

Two manual mapping tables curate cases where cascaded matching produces wrong
results:

- `data/processed/manual_chebi_mappings.tsv` — chemistry abbreviations to canonical ChEBI IDs (TMAO, EGCG, EPA, DHA, LPS, betaine, SCFA, NSAID; 9 entries)
- `data/processed/bolte_food_mappings.tsv` — FFQ-style food names to FoodOn-mappable labels (~30 entries)
- `data/processed/foodb_compound_allowlist.tsv` — 38 IBD-relevant compounds with FooDB canonical names

A verification script (`scripts/verify_manual_mappings.py`) confirms every
manual mapping ID exists in the current ontology release.

### 2.4 Validation

The normalization layer was validated by spot-checking IBD-canonical entities:
- 27/27 IBD-relevant ChEBI compounds resolve cleanly (manual mappings + cascaded matcher)
- 8/8 IBD-relevant microbes resolve including renamed taxa (Lactobacillus rhamnosus -> Lacticaseibacillus rhamnosus, Ruminococcaceae -> Oscillospiraceae)
- 8 of 9 well-known compounds spot-checked against FooDB ChEBI mappings produce correct canonical IDs

---

## 3. Curated Database Ingestions

### 3.1 Disbiome (microbe-disease associations)

**Source:** Disbiome experiment endpoint (https://disbiome.ugent.be:8080/experiment)
**Version:** Retrieved 2026-05-10
**License:** Open access (academic)
**Total entries in source:** 10,866
**IBD-filtered entries:** 765 (7.0% of total)

**Processing:**
- Filtered to disease names matching IBD vocabulary (Crohn's, ulcerative colitis, IBD unspecified, inactive CD)
- Used Disbiome's pre-curated `organism_ncbi_id` field directly (98.6% coverage)
- Mapped 1 entry without NCBI ID via cascaded matcher fallback
- Mapped disease names to Disease Ontology IDs (DOID:8778, DOID:8577, DOID:0050589)
- Predicates derived from `qualitative_outcome` field (Reduced -> decreased_in, Elevated -> increased_in)

**Confidence scoring:**
- Baseline 0.85 (Disbiome is curated)
- +0.03 if quantitative ratio reported
- -0.05 if method is qPCR or DGGE (less robust than 16S/shotgun)

**Output:** 754 triples (data/processed/triples_disbiome.tsv)

**Distribution:**
- 464 decreased_in / 290 increased_in
- 475 Crohn's disease / 217 ulcerative colitis / 55 IBD-unspecified / 7 inactive CD
- Top organisms: F. prausnitzii (29), Roseburia (16), Bifidobacterium (14)

**Validation:** Canonical IBD finding reproduces — F. prausnitzii decreased_in
Crohn's disease across 21/21 independent Disbiome entries (unanimous).

### 3.2 FooDB (food-bioactive compound)

**Source:** FooDB bulk CSV dump (https://foodb.ca/public/system/downloads/foodb_2020_4_7_csv.tar.gz)
**Version:** 2020-04-07 release
**License:** CC BY-NC 4.0
**Total source size:** 953 MB compressed (note: file is plain tar despite .tar.gz extension)
**Total compounds:** 70,477
**Total food-compound association rows:** 5,145,533

**Processing:**
- Allow-list filter: 38 IBD-relevant compounds curated by name (anti-inflammatory polyphenols, SCFAs, omega-3s, fibers, FODMAPs, TMAO precursors)
- Classified filter: 3,772 compounds in IBD-relevant superklasses (Lipids, Phenylpropanoids, Organic acids, Organoheterocyclic, etc.)
- ChEBI mapping quality gate: 2,410 of 3,786 candidates (63.7%) successfully resolved to ChEBI IDs via cascaded ontology lookup
- Food resolution: 753 of 992 foods (75.9%) resolve to FoodOn IDs via cascaded matcher
- Concentration-aware filtering:
  - Zero-concentration rows dropped (below detection limit, not biological presence)
  - Non-zero measurements kept at confidence 0.85-0.90
  - Presence-only rows (NaN concentration) kept at confidence 0.70-0.75
- Linnean binomial filter: dropped 4,027 triples where food label was a taxonomic species name (e.g., Sus scrofa domesticus) instead of a food product

**Confidence scoring:**
- Baseline 0.80
- +0.05 if compound is in IBD allow-list
- +0.05 if standard_content (normalized concentration) available
- -0.10 if presence-only

**Output:**
- Raw output: 218,568 triples (data/processed/triples_foodb.tsv)
- Filtered output: 18,772 triples (data/processed/triples_foodb_filtered.tsv) — allow-list compounds, food products only

**Bug fix history (documented for reproducibility):**
- v1: Misinterpreted FooDB's CompoundSynonym schema. The synonym_source='ChEBI' field tags synonyms that ChEBI lists, not synonyms that ARE ChEBI IDs. Initial parser concatenated digits from synonym strings producing garbage IDs.
- v2: Replaced with proper cascaded ChEBI ontology lookup on compound names. 8 of 9 spot-checked compounds resolve to canonical IDs.
- v3: Added concentration-aware filtering to distinguish trace amounts from real measurements.

**Validation:** Well-known associations correctly captured — EPA in Atlantic salmon, quercetin in highbush blueberry, genistein in soybean and soy products, sulforaphane in broccoli and brassicas.

### 3.3 Bolte et al. 2021 (diet-microbiome-marker meta-analysis)

**Source:** Supplementary data from Bolte LA et al. Gut 70:1287-1298 (2021). DOI: 10.1136/gutjnl-2020-322670
**Cohort:** 1,425 individuals across 4 cohorts (healthy controls, Crohn's disease, ulcerative colitis, IBS)
**Method:** Inverse-variance meta-analysis with cohort-pooled effect sizes

**Significance criterion:** FDR < 0.05 AND Het.Pval > 0.05 (significant pooled effect AND consistent across cohorts; paper's published criterion)

**Processing:**
- Three supplementary tables parsed:
  - S4 (725 rows): food cluster -> bacterial cluster
  - S5 (50 rows): food cluster -> inflammatory marker (calprotectin, chromogranin A)
  - S7 (28,000 rows): individual food -> taxon
- Numeric coercion for mixed-type Het.Pval column (some rows have 'NS' string instead of float)
- MetaPhlAn-style taxa strings (k__Bacteria.p__Firmicutes...) parsed to most-specific rank
- Manual food name mapping table for FFQ-style identifiers (yoghurt_lf, group_dairy, etc.)
- Confidence scaled by FDR strength (0.80-0.95)

**Output:** 132 triples (data/processed/triples_bolte2021.tsv)
- 11 from S4 (cluster-level)
- 7 from S5 (food -> calprotectin/ChrA) — **clinically most significant**
- 114 from S7 (individual food -> microbe)

**Skipped (acceptable, documented limitations):**
- 245 S7 rows where FFQ food name had no FoodOn entry (e.g., 'snack_savoury_hot', 'fish_prepared_fat')
- Nutrient-quantity associations (carb_g/d, plant_protein_g/d) not modeled as Food entities; deferred to potential 'DietaryVariable' entity type

**Validation:** S5 results align with established IBD nutrition guidance — pro-inflammatory pattern (Meat_Potatoes_Gravy, Fastfood) increases calprotectin; anti-inflammatory pattern (Fish_Nuts) decreases calprotectin.

### 3.4 FODMAP Classifications (multi-source consensus)

**Source:** Multi-source consensus from open educational materials:
- Monash University FODMAP educational pages
- Healthline FODMAP food list (2022)
- Alberta Health Services Low FODMAP Eating
- UVA Digestive Health Center FODMAP guide
- IBSDiets.org FODMAP Food List
- SelfDecode FODMAP Food List

**Rationale:** Monash's full quantitative database is paywalled in their mobile
app. We curated a TSV of well-known foods where 3+ sources agree on
classification, providing high-confidence binary high/low FODMAP categorization
without paywalled content.

**Processing:**
- ~95 foods classified as either "high in {fructans|lactose|fructose|sorbitol|mannitol|GOS}" or "low FODMAP"
- All FODMAP components resolved to ChEBI IDs (lactose:17716, D-fructose:28645, sorbitol:30911, D-mannitol:16899, fructan:24482, oligosaccharide:24151)
- All food names resolved to FoodOn via cascaded matcher (86 of 96 mapped)

**Output:** 86 triples (data/processed/triples_fodmap.tsv)
- 47 has_high_FODMAP_content_of
- 39 is_low_FODMAP_food

**Skipped (acceptable, 10 entries):** Compound names without FoodOn entries (high fructose corn syrup, lactose-free milk, dark chocolate). Phase C LLM extraction may recover some via primary literature.

### 3.5 Deferred Sources

**gutMDisorder v2.0:** Server (bio-annotation.cn) actively refuses connections on ports 80/443 with TCP "Connection refused". Substantial overlap with Disbiome on microbe-disease content; Phase C LLM extraction from PubMed will partially recover the underlying primary literature.

**KEGG (microbe-pathway-metabolite):** Pending. Programmatic access via KEGG REST API. Will add ~5,000 triples covering metabolic pathway annotations for SCFA production, secondary bile acid metabolism, tryptophan metabolism, sulfur metabolism. Will be added in the next ingestion phase.

---

## 4. Bug History and Lessons Learned

Three significant bugs were caught during validation and are documented for
reproducibility:

1. **FooDB ChEBI ID parser (caught at v1 validation):** Initial assumption that
   `synonym_source='ChEBI'` rows contained ChEBI IDs was wrong; they contain
   alternative chemical names sourced from ChEBI's records. The fix was to
   replace ad-hoc digit extraction with proper cascaded ontology lookup. The bug
   would have produced 18K triples with garbage object IDs; caught by spot-checking
   well-known compounds (EPA expected CHEBI:28364, observed CHEBI:58111417).

2. **Mixed-type column comparison in Bolte 2021 (caught at first run):** Bolte's
   Het.Pval column contains both float p-values and 'NS' string markers for
   "not significant". Direct numeric comparison failed. Fix: `pd.to_numeric(...,
   errors='coerce')` converts non-numeric values to NaN, dropped by the
   significance filter.

3. **Concentration-zero treatment in FooDB (caught at v2 validation):** Foods
   with `orig_content == 0` were initially treated as "containing trace amounts"
   when they actually represent "below detection limit". Fix: distinguish zero
   measurements (drop) from null measurements (presence-only, lower confidence).

These bugs reinforce the importance of sample-and-inspect validation. Every
ingestion should reproduce canonical findings (e.g., F. prausnitzii decreased
in CD, EPA in salmon, lactose in dairy) before being trusted at scale.

---

## 5. Provenance and Reproducibility

Every triple in DietIBD-KG carries:
- Source database/paper identifier
- Source-internal ID for the specific record
- Publication DOI where applicable
- Confidence score with source-specific scoring rationale
- Method/sample context (e.g., '16S rRNA sequencing', 'Faeces')

All ingestion scripts, normalization code, and curated mapping tables are
maintained under version control. Bulk source data is referenced by URL and
version date in the methods, not redistributed (per FooDB CC BY-NC license).
The ingestion pipeline is fully reproducible from public URLs and the
included scripts.
