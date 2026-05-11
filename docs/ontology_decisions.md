
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
