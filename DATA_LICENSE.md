# Data License

The **code** in this repository is licensed under the MIT License (see `LICENSE`).
The **data** — the DietIBD-KG knowledge graph files, including
`data/processed/nodes_consolidated.tsv` and `data/processed/edges_consolidated.tsv`
and any released graph export — is licensed under the
**Creative Commons Attribution 4.0 International License (CC BY 4.0)**.

You are free to share and adapt the data for any purpose, provided you give
appropriate credit. Full licence text: https://creativecommons.org/licenses/by/4.0/

## Attribution

Please cite:

> Thoniyot S, Balakrishnan V. DietIBD-KG: a dual-layer diet–microbiome–IBD
> knowledge graph. 2026. https://github.com/sthoniyot/DietIBD-KG

## Source data

DietIBD-KG integrates content derived from third-party resources, each governed
by its own terms. Parties redistributing or reusing the data should consult the
original terms of:

- **FooDB** (https://foodb.ca) — food composition
- **Disbiome** (https://disbiome.ugent.be) — microbe–disease associations
- **Bolte et al. 2021**, *Gut* (https://doi.org/10.1136/gutjnl-2020-322670) — diet–microbiome cohort
- **FODMAP** consensus compilation
- **Literature-derived assertions** extracted from PubMed / PMC abstracts; each
  literature edge carries its supporting PMID(s) and a verbatim evidence span.

## KEGG (excluded from this release)

KEGG-derived pathway content is **not** included in this release, because the
KEGG database is not redistributable under these terms. The code to regenerate
the pathway layer from KEGG is provided in `src/ingestion/ingest_kegg_pathways.py`;
running it requires your own KEGG licence/access. See the manuscript's
*Limitations* and *Availability of data and materials* sections for details.
