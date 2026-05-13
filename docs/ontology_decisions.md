
## Decision: FooDB Compound Coverage Gaps Documented

**Date:** 2026-05-10

**Context:** During FooDB allow-list curation, we discovered that several biologically important IBD-relevant compounds are absent from FooDB or only present as derivatives.

**Compounds NOT in FooDB (must be sourced elsewhere):**
- **Docosahexaenoic acid (DHA)** — completely absent. No 'hexaenoic' or 'cervonic' entries.
- **Plain Butyric acid / Propionic acid** — only conjugated derivatives (e.g., Indole-3-butyric acid, 2-Hydroxybutyric acid). Note: Acetate IS present as id=30807. SCFAs are partially covered.
- **Plain Linoleic acid** — only oxidized derivatives (Hydroperoxy-, Nitro-).
- **Plain Resveratrol** — only stereoisomers (trans-resveratrol, (Z)-Resveratrol). We use trans-resveratrol as canonical.
- **Plain Epicatechin** — only conjugates (epicatechin gallate, epicatechin glucoside).
- **Indole-3-carbinol** — completely absent.
- **Plain Pinoresinol** — only methylated/acetoxy variants.

**Mitigation strategy:**
1. For the FooDB ingestion (this paper), accept these gaps and use the 38 compounds that match cleanly.
2. Document the gaps in the methods section.
3. Phase C LLM literature extraction from PubMed will recover most missing compounds via published papers ("DHA reduces gut inflammation in CD" etc.).
4. KEGG metabolic pathway ingestion will add canonical SCFAs (butyrate, propionate) via metabolic pathway maps.
5. Future: consider Phenol-Explorer database (dedicated polyphenol resource) for cleaner polyphenol coverage.

**Conclusion:** FooDB is an imperfect source for bioactive compounds. It excels at flavonoid glycosides, lipid derivatives, and stereo-explicit canonical forms but has systematic gaps for the simplest biologically-discussed parent compounds. This shapes our ingestion strategy.

## Phase B Status Snapshot (2026-05-10 end of session)

**Curated database ingestions complete:**

| Source | Triples | File |
|---|---|---|
| Disbiome | 754 | triples_disbiome.tsv |
| FooDB (filtered) | 18,772 | triples_foodb_filtered.tsv |
| Bolte 2021 | 132 | triples_bolte2021.tsv |
| FODMAP consensus | 86 | triples_fodmap.tsv |
| **Total Phase B** | **19,744** | |

**Remaining for Phase B:**
- KEGG (microbe-pathway-metabolite) — ~5,000 triples expected, programmatic via REST API
- (Optional) Phenol-Explorer for cleaner polyphenol coverage

**Phase C planned next:**
- PubMed LLM extraction (~20,000-30,000 additional triples)

**Repository commits to date:** 7 (f5d7551, 462a478, 5ac58bf, 9cddb23, 6863e58, a02fb5b, c271f14)

## Phase B.5 Neo4j Load (2026-05-13)

**KG state:** 1,476 nodes, 8,108 relationships loaded into Neo4j.

**Compression: 40%** (20,252 source triple rows compressed to 8,108 unique
edges with aggregated provenance via evidence_count and sources fields).

**Schema:** 8 node labels (Food, Bioactive, Microbe, Pathway, IBD_Outcome,
Metabolite, Cytokine, Disease), 11 relationship types, uniqueness constraint
on id per label.

**Reconciliations applied:** 7 canonical mappings (3 ChEBI acid->anion,
4 NCBI genus->species-placeholder). See data/processed/canonical_id_map.tsv

**Curation fix during load:** Two rows removed from
data/processed/fodmap_classifications.tsv that incorrectly typed compounds
as foods: inulin (a fructan polysaccharide) and sucrose (a disaccharide).
Both are correctly present in the KG as Bioactive entities via FooDB/KEGG.
FODMAP triples dropped from 86 to 84.

**Validation queries confirmed:**
- F. prausnitzii DECREASED_IN Crohn's: 21 sources (canonical IBD finding)
- Quercetin in apple/tea/berries/grape wine (textbook polyphenol distribution)
- Butanoate metabolism captures real SCFA biochemistry intermediates
- Bolte 2021 calprotectin findings preserved (Meat_Potatoes_Gravy increases,
  Fish_Nuts decreases, etc.)
- Tryptophan pathway multi-hop traversals work (food->indole-3-acetate->pathway)
- 0 isolated nodes
- 0 type mismatches after FODMAP fix

**Documented KG gaps (to be filled by Phase C):**
- Butyric acid (CHEBI:17968): exists via KEGG pathway, 0 food edges. FooDB
  does not track butyric acid as a content compound. Butter is universally
  known to contain butyric acid; Phase C extraction will recover this.
- DHA (CHEBI:28125): similar gap. Present in KEGG, absent from FooDB foods.
- Plain propionic acid: same pattern as butyric.
- Plain resveratrol: only trans-resveratrol variant present from FooDB.
